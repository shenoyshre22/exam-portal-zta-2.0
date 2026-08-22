"""
locustfile.py

Single-purpose Locust benchmark: how much latency does SentinelGate's policy
enforcement add on top of the unpatched baseline gateway, at one realistic
load level? This is deliberately NOT a multi-baseline, multi-load-point
throughput study (see CHANGES.md, "Scope lock" section, for why that was
rejected) -- it's one honest number, measured the same way twice: once
against the unpatched gateway, once against the patched one.

Usage -- run the exact same command against both stacks, one at a time:

    # 1. Baseline (unpatched):
    #    cd baseline_unpatched/  &&  docker compose up --build   (separate terminal)
    locust -f locustfile.py --host http://localhost:8000 --headless \
        -u 100 -r 10 -t 3m --csv=baseline_results

    # 2. Stop the baseline (docker compose down), then Patched:
    #    cd exam-portal-zta-main/  &&  docker compose up --build   (separate terminal)
    locust -f locustfile.py --host http://localhost:8000 --headless \
        -u 100 -r 10 -t 3m --csv=patched_results

Compare baseline_results_stats.csv vs patched_results_stats.csv: p50/p95/p99
latency and RPS, per endpoint and in aggregate. Or drop --headless and open
http://localhost:8089 for the interactive Locust web UI instead of CSV output.

Flags used above (one load level, matching the locked scope):
    -u 100   100 concurrent simulated users
    -r 10    ramp up 10 users/second
    -t 3m    run for 3 minutes
"""

import random
import string
import threading

import requests
from locust import HttpUser, task, between, events

TEACHER = {"username": "teacher1", "password": "password1"}

_exam_id = None
_setup_lock = threading.Lock()


@events.test_start.add_listener
def prepare_exam(environment, **kwargs):
    """
    Runs once before load generation starts (not once per simulated user).
    Creates a shared exam + 3 MCQs as teacher1 so simulated students have
    something real to view/submit against. This endpoint's behavior is
    identical on the baseline and patched gateway, so it's safe to reuse
    against either stack unchanged.
    """
    global _exam_id
    with _setup_lock:
        if _exam_id is not None:
            return

        base = environment.host
        r = requests.post(f"{base}/auth/login", json=TEACHER)
        r.raise_for_status()
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        r = requests.post(f"{base}/exams", headers=headers, json={
            "title": "Locust Benchmark Exam", "description": "auto-created for load test",
            "total_marks": 30, "duration_minutes": 30,
        })
        r.raise_for_status()
        _exam_id = r.json()["id"]

        for i in range(3):
            requests.post(f"{base}/questions/add-mcq", headers=headers, json={
                "exam_id": _exam_id, "question_text": f"Bench question {i + 1}?",
                "option_a": "A", "option_b": "B", "option_c": "C", "option_d": "D",
                "correct_answer": "A",
            })
        print(f"[locust setup] created exam_id={_exam_id}")


def _random_username():
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"loadtest_{suffix}"


class ExamStudent(HttpUser):
    """
    The dominant traffic pattern: a student browsing exams, viewing questions,
    submitting answers. Weighted heavily -- this is what the policy check runs
    on for the large majority of real requests, so it should dominate the
    latency numbers, not teacher/admin actions.
    """
    wait_time = between(0.5, 2.0)
    weight = 5

    def on_start(self):
        self.username = _random_username()
        self.client.post("/auth/signup", json={
            "username": self.username, "password": "loadtestpass123", "role": "student",
        }, name="/auth/signup")
        r = self.client.post("/auth/login", json={
            "username": self.username, "password": "loadtestpass123",
        }, name="/auth/login")
        self.token = r.json().get("access_token", "")
        self.headers = {"Authorization": f"Bearer {self.token}"}

    @task(3)
    def list_exams(self):
        self.client.get("/exams", headers=self.headers, name="/exams")

    @task(5)
    def view_questions(self):
        if _exam_id:
            self.client.get(f"/questions/{_exam_id}", headers=self.headers, name="/questions/{exam_id}")

    @task(2)
    def submit_answer(self):
        # Each simulated student answers a random question; repeats past the
        # first will legitimately 400 ("already submitted"). That's expected
        # and fine -- this measures gateway/policy latency, not business-rule
        # success rate, and the same behavior applies identically to both
        # the baseline and patched runs.
        if not _exam_id:
            return
        qid = str(random.randint(1, 3))
        self.client.post("/submit-answer", headers=self.headers, json={
            "student_id": self.username, "exam_id": str(_exam_id),
            "question_id": qid, "answer": "A",
        }, name="/submit-answer")

    @task(1)
    def view_own_results(self):
        self.client.get(f"/results/{self.username}", headers=self.headers, name="/results/{student_id}")


class Teacher(HttpUser):
    """
    A smaller share of traffic. Real exam-time load is mostly students, not
    teachers -- kept low-weight so the headline latency numbers reflect the
    common case, not a teacher-heavy mix.
    """
    wait_time = between(2.0, 5.0)
    weight = 1

    def on_start(self):
        r = self.client.post("/auth/login", json=TEACHER, name="/auth/login")
        self.token = r.json().get("access_token", "")
        self.headers = {"Authorization": f"Bearer {self.token}"}

    @task
    def list_exams(self):
        self.client.get("/exams", headers=self.headers, name="/exams")
