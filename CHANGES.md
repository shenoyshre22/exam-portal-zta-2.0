# SentinelGate patch — changes vs. the June 2026 audit report

Applied against the repo state as of this upload (not the original audit snapshot —
some findings had already shifted; see "repo drift" notes below).

## Priority 0 — Gateway becomes a real PEP

**New: `api_gateway/policy.py`**
Centralized `(method, route) -> allowed roles` table (`POLICY`), a resource-ownership
checker (`OWNERSHIP_PARAMS`), and a response filter that strips `correct_answer` from
student-facing question payloads.

**`api_gateway/main.py`**
- Every protected route now calls `enforce()` before proxying: policy check, ownership
  check, and a telemetry event (`ALLOWED`/`BLOCKED`) emitted either way. Previously the
  gateway called `validate_token` and ignored the returned role entirely (B9/B10).
- `/submit-answer`, `/submissions/{id}`, `/log-event`, `/logs`, `/logs/{id}` now forward
  the bearer token downstream — previously dropped, which is what made Attack 2/3 in
  the audit (reading any student's submissions/logs) work even before you consider B6/B7.
- `/questions/{exam_id}` response is passed through `filter_question_fields()` — fixes B5.

## Priority 1 — trust model

- **B8** (hardcoded `internal-service-token`): all five call sites
  (`question_service`, `result_service`, `evaluation_service` ×2, `api_gateway`) now read
  `INTERNAL_SERVICE_TOKEN` from the environment. Docker Compose injects it from `.env`.
  Fallback literal is still in code for bare (`python main.py`) local runs — copy
  `.env.example` to `.env` for the real deployment. Documented as a scope limitation:
  true mTLS/short-lived service identity is out of scope for this project.
- **B4** (`SECRET_KEY` default): `login_service` now receives `SECRET_KEY` from Compose.
  Same fallback-for-local-dev caveat as above.
- **B6** (Submission service, zero auth): new `submission_service/auth_client.py`.
  `POST /submit-answer` now requires a token and rejects a student submitting under
  someone else's `student_id` (was the identity-spoofing hole in 2.6). `GET
  /submissions/{id}` now enforces ownership for students.
- **B7** (Logging service, zero auth): new `logging_service/auth_client.py`. Writes
  require any authenticated caller (closes log-poisoning). `GET /logs` is teacher-only.
  `GET /logs/{user_id}` enforces per-user ownership for students.

## Priority 2 — correctness

- **B1** (duplicate `verify_token`, dead first definition): fixed in
  `question_service/auth_client.py`, `result_service/auth_client.py`,
  `evaluation_service/auth.py`. One definition each, internal-token check first.
- **B2** (dead `log_event` after `return`): **repo drift note** — this was already fixed
  in `evaluation_service/main.py` by the time this zip was pulled, but `result_service`
  had only had a comment added (`# after existing record update`) without moving the
  code. Now actually moved above `return existing`, so `RESULT_UPDATED` fires.
- **B3** (`localhost` URLs break in Docker): **repo drift note** — DB paths had already
  been migrated to `/app/data/...` (Docker-volume-aware) but every inter-service HTTP
  call still hardcoded `http://localhost:PORT`. All URLs across `auth_client.py`,
  `logger.py`, and the two direct service-to-service callers
  (`result_service/main.py` -> evaluation, `evaluation_service/main.py` -> submission/
  question) now default to the Compose container names (`http://login_service:5000`
  etc.) via `os.getenv(..., default)`, so they still work if you run bare too.

## Network isolation — Attack 4 closed

The original audit's most severe finding (Attack 4, "direct service bypass") relied on
every service port being published to the host — an attacker on the same network could
hit `question_service:5001` directly and skip the gateway/policy entirely. This was
previously listed below as a deliberately accepted limitation. It's now fixed:
`docker-compose.yml` no longer publishes host ports for any of the 7 backend services —
only `api_gateway` (port 8000) is reachable from outside Docker. Inter-service calls are
unaffected: they already communicated over the internal `exam_network` bridge by
container name (`http://login_service:5000`, etc.), which Docker resolves regardless of
whether a host port is published. This closes the gap without touching any service code.

**Practical effect on local testing**: `curl http://localhost:5001/...` no longer works —
everything now has to go through `http://localhost:8000/...` (the gateway), which is the
correct behavior to be testing anyway.

Two related items were considered and **not** adopted:
- Local JWT decoding in every service instead of the network call to `/verify-token` —
  would require distributing `SECRET_KEY` to all 7 services instead of just
  `login_service`, trading one network dependency for a wider secret-exposure surface.
  Real pattern, but not a net security improvement here; noted as future work instead.
- A separate `X-Internal-Secret` header check — functionally duplicates the
  `INTERNAL_SERVICE_TOKEN` Bearer-token check already in place since the B8 fix. Not
  implemented, since it would be the same protection under a different name.

## Not touched (deliberately out of scope)
- `question_service`'s response is only filtered at the gateway, not inside the service
  itself. That's intentional: it's the point of the paper (centralize enforcement at the
  PEP rather than duplicate it per-service). This used to mean anyone hitting
  `question_service:5001` directly got the raw answer key — closed now by the network
  isolation fix above, since that port is no longer reachable from outside Docker.

## Scope lock — anomaly detection & benchmarking track (post-patch decision)

A later proposal suggested adding OPA (policy-as-code), migrating SQLite → Postgres,
and running a live in-memory Isolation Forest that scores every request in the hot path,
alongside a 3-baseline / 4-load-level Locust benchmarking study. **Rejected, in full.**
None of the three changes add capability the gateway doesn't already have (RBAC/IDOR/
ownership enforcement is already centralized in `policy.py`), each adds real
infrastructure and re-testing risk this late in the timeline, and live scoring reopens a
"real-time monitoring" approach already decided against in favor of the simpler,
reproducible offline-log-then-analyze pattern.

**What was kept from that proposal** — it wasn't a bad idea end-to-end, just oversized:

1. **Architecture** — unchanged. Existing Python `policy.py` logic and SQLite testbed stay
   exactly as patched above. No OPA, no Postgres.
2. **Telemetry & feature engineering** — the gateway's existing `ALLOWED`/`BLOCKED` event
   stream (already emitted per request, see Priority 0 section above) is exported and
   three features are computed **offline, in pandas**, not live in the gateway process:
   `req_count_5s`, `denied_ratio`, `route_entropy`. See
   `feature_engineering.py` — no new logging code needed, this reads the schema that
   already exists.
3. **ML pipeline** — Isolation Forest trained and scored offline against the feature
   vectors above, producing Precision/Recall/F1/ROC-PR against labeled attack traffic
   from the controlled attack-scenario runs. Same as the original plan, unchanged.
4. **Benchmarking** — one Locust run, one load level, single purpose: show the gateway's
   `enforce()` policy check adds negligible latency versus the unpatched blind-proxy
   baseline. Not a 3-baseline × 4-load-level throughput study.
5. **Paper framing** — live in-memory ML inference goes in Discussion/Future Work as an
   extension, not in Results. This keeps the abstract's anticipatory language ("Isolation
   Forest-based behavioral anomaly detection") accurate to what was actually measured.

## Hardening pass — cheap fixes for reviewer credibility

Three small additions, none touching architecture or timeline, that close the easiest
lines of attack a reviewer would take:

- **`api_gateway/policy_config.json`** (new) + `policy.py` updated to load it. The
  route/role table is no longer hardcoded in source — it's an external JSON file the
  gateway reads at startup, with a built-in fallback only for local dev without the file
  present. Addresses "static, hardcoded policy" as a literal criticism without adopting
  a policy-as-code engine.
- **`anomaly_detection.py`** (new) — runs a naive fixed-threshold rule *and* the
  Isolation Forest on the same feature set, reports Precision/Recall/F1/ROC-AUC for
  both side by side. If the Isolation Forest doesn't clearly beat the naive rule on the
  real data, that's reported as-is rather than tuned away — it's a legitimate finding
  either way and preempts "why not just use a threshold?" as a review comment.
- **Limitations paragraph** (below) — stated once, explicitly, rather than left for a
  reviewer to discover.

## Limitations (for the paper's Discussion/Limitations section)

SentinelGate's policy table is static and role-based rather than dynamically evaluated
or context-aware (time-of-day, device posture, request history beyond the three
engineered features); it is externally configurable but not adaptive. Anomaly detection
runs offline against exported logs rather than scoring requests in the hot path, so
detection is necessarily after-the-fact rather than preventive — acceptable for a
research evaluation of detection quality, not for production incident response.
Evaluation is conducted on a single-node, seven-service testbed with SQLite and
synthetic/scripted traffic; results characterize the mechanism's behavior on this scale
and traffic pattern, not its behavior under production load or against adversarial
traffic engineered specifically to evade the three chosen features. Service-to-service
trust still relies on a single shared static token rather than per-service cryptographic
identity (e.g. mTLS) — moved out of source control via environment variables, but not
architecturally distinct per service. These are stated as scope boundaries of a
lightweight, reproducible prototype, not oversights; extending toward dynamic/context-
aware policy, real-time scoring, and stronger service identity is noted as future work.


