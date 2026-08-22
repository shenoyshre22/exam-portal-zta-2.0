# SentinelGate — Windows Runbook

Everything below assumes: zip extracted to `D:\`, using **Git Bash** as the primary
terminal (installed with Git for Windows). Git Bash maps `D:\` to `/d/` — that's the
one path quirk to remember throughout.

After extracting, you should have two folders side by side:
```
D:\exam-portal-zta-main      <- the patched project (main work)
D:\baseline_unpatched        <- original vulnerable code (for the before/after benchmark only)
```

---

## Part 0 — One-time installs (skip anything already done)

| Tool | Why | Where to get it |
|---|---|---|
| Docker Desktop | Runs all 8 services | docker.com/products/docker-desktop — keep "WSL 2" checked during install |
| Git for Windows | Gives you Git Bash | git-scm.com/download/win |
| Python 3.12 | Runs the analysis scripts | python.org/downloads — **check "Add to PATH"** during install |
| Python 3.11 | Runs Locust only (3.12 has a known bug with it) | python.org/downloads — pick any 3.11.x build, also check "Add to PATH" |

After installing, open **Git Bash** (search Start menu) and confirm all four:
```bash
docker --version
docker compose version
python --version
py -0
```
`py -0` should list both `3.12` and `3.11`.

**Launch Docker Desktop** and leave it running in the background for everything below — nothing works if it's closed.

---

## Part 1 — Extract and configure secrets (Terminal 1)

Open Git Bash. Either:
- Right-click inside `D:\exam-portal-zta-main` in File Explorer → **"Open Git Bash here"**, or
- Open Git Bash normally, then `cd /d/exam-portal-zta-main`

```bash
cd /d/exam-portal-zta-main
cp .env.example .env
openssl rand -hex 32
openssl rand -hex 32
```
Run that last line twice — two different random strings print. Open `.env`:
```bash
notepad .env
```
Paste the first string after `SECRET_KEY=`, the second after `INTERNAL_SERVICE_TOKEN=`. Save, close.

---

## Part 2 — Start the patched stack (keep this terminal open)

Still in Terminal 1, same folder:
```bash
docker compose up --build
```
First run takes a few minutes. **Leave this window open and running** — it's streaming logs from all 8 containers. Everything else below happens in a **second** Git Bash window.

---

## Part 3 — Open Terminal 2 and set up the analysis venv

Open a new Git Bash window (right-click in `D:\exam-portal-zta-main` → "Open Git Bash here" again, or Start menu → Git Bash, then `cd /d/exam-portal-zta-main`).

```bash
cd /d/exam-portal-zta-main
curl http://localhost:8000/health
```
Expect `{"status":"API Gateway Running"}` — confirms Docker is actually serving requests before you go further.

Create the venv (use `py -3`, not plain `python` — see below for why):
```bash
py -3 -m venv venv
source venv/Scripts/activate
pip install -r requirements-analysis.txt requests
```
Prompt should now show `(venv)`. If venv creation ever silently seems to do nothing — it's not silent-failing, it just doesn't print anything on success. Run `ls` and check for a `venv/` folder to confirm.

> **Why `py -3` and not `python`**: on some Windows setups, Git Bash's `python` resolves to MSYS2's bundled Python instead of your real python.org install, which can't install pandas/scikit-learn (fails trying to compile from source). `py -3` uses the Windows Python Launcher and reliably picks the right one. Only matters when *creating* the venv — once it's activated, plain `python`/`pip` inside it are correct.

---

## Part 4 — Generate real traffic (Terminal 2, venv active)

```bash
python run_attack_scenarios.py
```
Takes 1-2 minutes. Watch for `[expected]` tags on the attack attempts — confirms the 403s are firing correctly.

---

## Part 5 — Export logs and run the offline ML pipeline (Terminal 2)

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "teacher1", "password": "password1"}'
```
Copy the `access_token` from the response, then:
```bash
TEACHER_TOKEN=""eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZWFjaGVyMSIsInJvbGUiOiJ0ZWFjaGVyIiwiZXhwIjoxNzg3MzA5OTY1fQ.nH1EmYt9Ch8bbvc4-nBH-Hmfa7xLi4BthEP5LudkCJE"
curl http://localhost:8000/logs -H "Authorization: Bearer $TEACHER_TOKEN" -o gateway_logs_raw.json
python -c "import pandas as pd, json; pd.DataFrame(json.load(open('gateway_logs_raw.json'))).to_csv('gateway_logs.csv', index=False)"
python feature_engineering.py --input gateway_logs.csv --output features.csv --attacker-users attacker1
python anomaly_detection.py --features features.csv --output metrics.json
```
Check `features.csv` — `attacker1`'s rows should show visibly higher `req_count_5s`/`denied_ratio`/`route_entropy` than `student1`'s.

---

## Part 6 — Locust benchmark (needs Python 3.11, separate venv)

Still Terminal 2, same folder:
```bash
deactivate
py -3.11 -m venv venv-locust
source venv-locust/Scripts/activate
pip install locust requests
python -c "import locustfile; print('OK')"
```
Must print `OK` — if it throws a `RecursionError`, the venv picked up 3.12 instead of 3.11; re-run the `py -3.11 -m venv venv-locust` step and double check `py -0` actually lists 3.11.

### 6a — Baseline run first

Stop the patched stack: go to **Terminal 1**, press `Ctrl+C`, then:
```bash
docker compose down
```
Open a **third** Git Bash window for the baseline stack:
```bash
cd /d/baseline_unpatched
cp .env.example .env 2>/dev/null || echo "no .env.example here, that's fine — baseline uses its insecure defaults on purpose"
docker compose up --build
```
Leave this running. Back in **Terminal 2** (venv-locust active):
```bash
cd /d/baseline_unpatched
locust -f locustfile.py --host http://localhost:8000 --headless -u 100 -r 10 -t 3m --csv=baseline_results
```
Takes 3 minutes. Produces `baseline_results_stats.csv` in `D:\baseline_unpatched`.

### 6b — Patched run

Terminal 3: `Ctrl+C`, then `docker compose down`. Switch to `D:\exam-portal-zta-main`, `docker compose up --build` again.

Terminal 2:
```bash
cd /d/exam-portal-zta-main
locust -f locustfile.py --host http://localhost:8000 --headless -u 100 -r 10 -t 3m --csv=patched_results
```
Produces `patched_results_stats.csv` in `D:\exam-portal-zta-main`.

Compare the two CSVs — p50/p95/p99 latency, RPS per endpoint. That delta is your measured overhead.

---

## Part 7 — Shutting everything down

Whichever terminal has `docker compose up` running: `Ctrl+C`, then:
```bash
docker compose down
```
Add `-v` (`docker compose down -v`) to also wipe the SQLite volumes for a clean slate next time.

---

## Quick reference — which terminal, which folder

| Step | Terminal | Folder |
|---|---|---|
| Secrets setup | 1 | `D:\exam-portal-zta-main` |
| `docker compose up` (patched) | 1 (stays open) | `D:\exam-portal-zta-main` |
| Health check, attack scripts, ML pipeline | 2 | `D:\exam-portal-zta-main` |
| `docker compose up` (baseline) | 3 (stays open) | `D:\baseline_unpatched` |
| Locust runs (both) | 2 (venv-locust active) | matches whichever stack is currently up |

Two Python environments, used for different things — don't mix them up:
- `venv` (Python 3.12) → `feature_engineering.py`, `anomaly_detection.py`
- `venv-locust` (Python 3.11) → `locust` only
