# SentinelGate — locked-scope execution plan

Supersedes the earlier 16–17 day estimate. No OPA, no Postgres, no live in-memory
scoring. Gateway/testbed code is already patched (see `CHANGES.md`) — this plan covers
what's left: attack scripts, telemetry export, offline ML, one latency benchmark, write-up.

## Phase 1 — Attack scenario scripts (2 days)
- Script the four attacks from the audit against the patched gateway: student→teacher
  privilege escalation (`/evaluate`, `/publish-result`), token replay, cross-student IDOR
  (`/submissions/{id}`, `/results/{id}`, `/logs/{id}`), and direct-port bypass (hitting a
  service on its host port instead of :8000).
- Run each against **both** the pre-patch gateway (checked out from git history / the
  original zip) and the patched one. This is your before/after attack table — the
  simplest, highest-value result in the paper, and it doesn't depend on anything below.
- Every run — pass or fail — should hit the gateway enough times to generate a realistic
  mix of ALLOWED/BLOCKED events for Phase 2.

## Phase 2 — Telemetry export (0.5 day)
- Add a small export step: pull the `logs` table from `logging_service` (via `GET /logs`
  as a teacher, or direct SQLite read) and dump to CSV with columns
  `id, user_id, service, event_type, description, timestamp`.
- No changes to the logging schema or gateway code — it already emits everything needed.

## Phase 3 — Feature engineering (1 day)
- Run `feature_engineering.py` (below) over the exported CSV to produce
  `req_count_5s`, `denied_ratio`, `route_entropy` per event, keyed by `user_id` and
  `timestamp`.
- Spot-check a few rows by hand against the raw log — cheap insurance against a silent
  windowing bug before it's baked into the ML results.

## Phase 4 — Offline Isolation Forest (2 days)
- Fit `IsolationForest` on the feature vectors. Label ground truth using the known
  attacker identities/time windows from Phase 1's attack runs (legitimate exam traffic
  = normal, attack-script traffic = anomalous).
- Report Precision, Recall, F1, and a ROC/PR curve against that labeling. Keep the model
  and its `contamination` parameter simple and documented — reviewers will ask about
  threshold choice more than about model sophistication.

## Phase 5 — Latency benchmark (1 day)
- Single Locust run, single load level (pick one that's realistic for a class-sized exam,
  e.g. 100–200 concurrent students), comparing the unpatched blind-proxy gateway vs. the
  patched policy-enforcing gateway.
- One metric that matters: p50/p95 latency delta attributable to `enforce()`. This is a
  "the safety doesn't cost you anything" footnote, not a throughput study — one graph,
  one paragraph.

## Phase 6 — Write-up (2–3 days + buffer)
- Results section: before/after attack table (Phase 1) + anomaly detection metrics
  (Phase 4) + latency overhead (Phase 5).
- Discussion/Limitations: shared static `INTERNAL_SERVICE_TOKEN` instead of per-service
  identity, host-exposed service ports, live in-memory scoring as future work.
- Reconcile abstract wording against what was actually measured before final submission.

**Total: ~8.5–9.5 days** of remaining work plus buffer, against whatever's left in your
window — comfortably inside it even with the earlier gateway-patching days already spent.
