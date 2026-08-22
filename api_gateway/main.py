import os
from fastapi import FastAPI, HTTPException, Header, Depends, UploadFile, File
import requests

from policy import authorize, enforce_ownership, filter_question_fields
from logger import log_event as emit_event

SERVICES = {
    "login": os.getenv("LOGIN_SERVICE_URL", "http://login_service:5000"),
    "question": os.getenv("QUESTION_SERVICE_URL", "http://question_service:5001"),
    "exam": os.getenv("EXAM_SERVICE_URL", "http://exam_service:5002"),
    "logging": os.getenv("LOGGING_SERVICE_URL", "http://logging_service:5003"),
    "submission": os.getenv("SUBMISSION_SERVICE_URL", "http://submission_service:5004"),
    "evaluation": os.getenv("EVALUATION_SERVICE_URL", "http://evaluation_service:5005"),
    "result": os.getenv("RESULT_SERVICE_URL", "http://result_service:5006"),
}
INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "internal-service-token")

app = FastAPI(title="SentinelGate API Gateway")


def proxy(method: str, url: str, payload=None, token: str = None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.request(method, url, json=payload, headers=headers, timeout=10)
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Downstream service unavailable")

    try:
        data = response.json()
    except ValueError:
        data = {"detail": response.text}

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=data)
    return data


def proxy_multipart(url: str, token: str, exam_id: int, upload: UploadFile):
    headers = {"Authorization": f"Bearer {token}"}
    files = {"file": (upload.filename or "questions.pdf", upload.file, upload.content_type or "application/pdf")}
    try:
        response = requests.post(url, params={"exam_id": exam_id}, headers=headers, files=files, timeout=20)
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Downstream service unavailable")

    try:
        data = response.json()
    except ValueError:
        data = {"detail": response.text}

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=data)
    return data


def validate_token(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        response = requests.get(
            f"{SERVICES['login']}/verify-token",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Login service unavailable")
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return response.json()


def enforce(method: str, route_template: str, user: dict, **path_params):
    """
    Single choke point: policy check + ownership check + telemetry.
    Every call is logged as ALLOWED or BLOCKED — this is what feeds the
    Isolation Forest analysis later, so blocked attempts show up in the data
    even when the caller never gets a response back.
    """
    try:
        authorize(method, route_template, user)
        enforce_ownership(method, route_template, user, **path_params)
    except HTTPException as exc:
        emit_event(user.get("username", "unknown"), "gateway", "BLOCKED", f"{method} {route_template} -> {exc.detail}")
        raise
    emit_event(user.get("username", "unknown"), "gateway", "ALLOWED", f"{method} {route_template}")


@app.get("/")
def root():
    return {"message": "SentinelGate API Gateway Running", "services": SERVICES}


@app.get("/health")
def health():
    return {"status": "API Gateway Running"}


# --- Auth routes (open — no token needed) ---

@app.post("/auth/signup")
def signup(payload: dict):
    return proxy("POST", f"{SERVICES['login']}/signup", payload)


@app.post("/auth/login")
def login(payload: dict):
    return proxy("POST", f"{SERVICES['login']}/login", payload)


@app.get("/auth/verify")
def auth_verify(user=Depends(validate_token)):
    return user


# --- Question routes ---

@app.get("/questions/{exam_id}")
def questions(exam_id: int, authorization: str = Header(default=""), user=Depends(validate_token)):
    enforce("GET", "/questions/{exam_id}", user, exam_id=exam_id)
    token = authorization.split(" ", 1)[1].strip()
    data = proxy("GET", f"{SERVICES['question']}/questions/{exam_id}", token=token)
    return filter_question_fields(data, user.get("role"))


@app.post("/questions/add-mcq")
def add_mcq(payload: dict, authorization: str = Header(default=""), user=Depends(validate_token)):
    enforce("POST", "/questions/add-mcq", user)
    token = authorization.split(" ", 1)[1].strip()
    return proxy("POST", f"{SERVICES['question']}/add-mcq", payload, token=token)


@app.post("/questions/upload-pdf")
def upload_pdf(exam_id: int, file: UploadFile = File(...), authorization: str = Header(default=""), user=Depends(validate_token)):
    enforce("POST", "/questions/upload-pdf", user)
    token = authorization.split(" ", 1)[1].strip()
    return proxy_multipart(f"{SERVICES['question']}/upload-pdf", token, exam_id, file)


# --- Exam routes ---

@app.post("/exams")
def create_exam(payload: dict, authorization: str = Header(default=""), user=Depends(validate_token)):
    enforce("POST", "/exams", user)
    token = authorization.split(" ", 1)[1].strip()
    return proxy("POST", f"{SERVICES['exam']}/exams", payload, token=token)


@app.get("/exams")
def list_exams(authorization: str = Header(default=""), user=Depends(validate_token)):
    enforce("GET", "/exams", user)
    token = authorization.split(" ", 1)[1].strip()
    return proxy("GET", f"{SERVICES['exam']}/exams", token=token)


@app.get("/exams/{exam_id}")
def get_exam(exam_id: int, authorization: str = Header(default=""), user=Depends(validate_token)):
    enforce("GET", "/exams/{exam_id}", user, exam_id=exam_id)
    token = authorization.split(" ", 1)[1].strip()
    return proxy("GET", f"{SERVICES['exam']}/exams/{exam_id}", token=token)


# --- Submission routes (token now forwarded; service itself also gets auth — see submission_service) ---

@app.post("/submit-answer")
def submit_answer(payload: dict, authorization: str = Header(default=""), user=Depends(validate_token)):
    enforce("POST", "/submit-answer", user)
    token = authorization.split(" ", 1)[1].strip()
    return proxy("POST", f"{SERVICES['submission']}/submit-answer", payload, token=token)


@app.get("/submissions/{student_id}")
def submissions(student_id: str, authorization: str = Header(default=""), user=Depends(validate_token)):
    enforce("GET", "/submissions/{student_id}", user, student_id=student_id)
    token = authorization.split(" ", 1)[1].strip()
    return proxy("GET", f"{SERVICES['submission']}/submissions/{student_id}", token=token)


# --- Evaluation routes ---

@app.post("/evaluate")
def evaluate(payload: dict, authorization: str = Header(default=""), user=Depends(validate_token)):
    enforce("POST", "/evaluate", user)
    token = authorization.split(" ", 1)[1].strip()
    return proxy("POST", f"{SERVICES['evaluation']}/evaluate", payload, token=token)


@app.get("/evaluations/{student_id}")
def evaluations(student_id: str, authorization: str = Header(default=""), user=Depends(validate_token)):
    enforce("GET", "/evaluations/{student_id}", user, student_id=student_id)
    token = authorization.split(" ", 1)[1].strip()
    return proxy("GET", f"{SERVICES['evaluation']}/evaluations/{student_id}", token=token)


# --- Result routes ---

@app.post("/publish-result")
def publish_result(payload: dict, authorization: str = Header(default=""), user=Depends(validate_token)):
    enforce("POST", "/publish-result", user)
    token = authorization.split(" ", 1)[1].strip()
    return proxy("POST", f"{SERVICES['result']}/publish-result", payload, token=token)


@app.get("/results/{student_id}")
def results(student_id: str, authorization: str = Header(default=""), user=Depends(validate_token)):
    enforce("GET", "/results/{student_id}", user, student_id=student_id)
    token = authorization.split(" ", 1)[1].strip()
    return proxy("GET", f"{SERVICES['result']}/results/{student_id}", token=token)


# --- Logging routes (token now forwarded; service itself also gets auth — see logging_service) ---

@app.post("/log-event")
def log_event_route(payload: dict, authorization: str = Header(default=""), user=Depends(validate_token)):
    enforce("POST", "/log-event", user)
    token = authorization.split(" ", 1)[1].strip()
    return proxy("POST", f"{SERVICES['logging']}/log-event", payload, token=token)


@app.get("/logs")
def logs(authorization: str = Header(default=""), user=Depends(validate_token)):
    enforce("GET", "/logs", user)
    token = authorization.split(" ", 1)[1].strip()
    return proxy("GET", f"{SERVICES['logging']}/logs", token=token)


@app.get("/logs/{user_id}")
def user_logs(user_id: str, authorization: str = Header(default=""), user=Depends(validate_token)):
    enforce("GET", "/logs/{user_id}", user, user_id=user_id)
    token = authorization.split(" ", 1)[1].strip()
    return proxy("GET", f"{SERVICES['logging']}/logs/{user_id}", token=token)
