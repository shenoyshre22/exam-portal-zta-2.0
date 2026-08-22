from logger import log_event
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String, Float, DateTime
import requests
from database import SessionLocal, engine, Base
from auth_client import verify_token, INTERNAL_SERVICE_TOKEN
import os

EVALUATION_SERVICE_URL = os.getenv("EVALUATION_SERVICE_URL", "http://evaluation_service:5005")

app = FastAPI(title="Result Service")


class Result(Base):
    __tablename__ = "results"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(String, index=True)
    exam_id = Column(String, index=True)
    score = Column(Integer)
    total = Column(Integer)
    percentage = Column(Float)
    grade = Column(String)
    generated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))  # FIXED


Base.metadata.create_all(bind=engine)


class ResultRequest(BaseModel):
    student_id: str
    exam_id: str


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# NEW — teacher only
def get_curr_teacher(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ", 1)[1].strip()
    user = verify_token(token)
    if user.get("role") != "teacher":
        raise HTTPException(status_code=403, detail="Teachers only")
    return user


# NEW — any logged in user, returns full user info
def get_curr_user(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ", 1)[1].strip()
    user = verify_token(token)
    return user


def grade_from_percentage(percentage: float) -> str:
    if percentage >= 90:
        return "A"
    if percentage >= 80:
        return "B"
    if percentage >= 70:
        return "C"
    if percentage >= 60:
        return "D"
    return "F"


def evaluate(student_id: str, exam_id: str):
    try:
        response = requests.post(
            f"{EVALUATION_SERVICE_URL}/evaluate",
            json={"student_id": student_id, "exam_id": exam_id},
            headers={"Authorization": f"Bearer {INTERNAL_SERVICE_TOKEN}"},
            timeout=10,
        )
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Evaluation service unavailable")

    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Unable to evaluate student")

    return response.json()


@app.get("/")
def root():
    return {"message": "Result Service Running"}


# FIXED — teacher only
@app.post("/publish-result")
def publish_result(payload: ResultRequest, db: Session = Depends(get_db), user=Depends(get_curr_teacher)):
    evaluation = evaluate(payload.student_id, payload.exam_id)

    score = int(evaluation.get("score", 0))
    total = int(evaluation.get("total", 0))
    percentage = float(evaluation.get("percentage", 0.0))
    grade = grade_from_percentage(percentage)

    existing = (
        db.query(Result)
        .filter(
            Result.student_id == payload.student_id,
            Result.exam_id == payload.exam_id,
        )
        .first()
    )

    if existing:
        existing.score = score
        existing.total = total
        existing.percentage = percentage
        existing.grade = grade
        existing.generated_at = datetime.now(timezone.utc)  # FIXED
        db.commit()
        db.refresh(existing)
        log_event(payload.student_id, "result", "RESULT_UPDATED", f"Grade {grade} for exam {payload.exam_id}")
        return existing

    result = Result(
        student_id=payload.student_id,
        exam_id=payload.exam_id,
        score=score,
        total=total,
        percentage=percentage,
        grade=grade,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    # after new record created
    log_event(payload.student_id, "result", "RESULT_PUBLISHED", f"Grade {grade} for exam {payload.exam_id}")
    return result


# FIXED — student sees own only, teacher sees anyone's
@app.get("/results/{student_id}")
def get_results(student_id: str, db: Session = Depends(get_db), user=Depends(get_curr_user)):
    if user["role"] == "student" and user["username"] != student_id:
        raise HTTPException(
            status_code=403,
            detail="You can only view your own results"
        )
    return db.query(Result).filter(Result.student_id == student_id).all()


@app.get("/health")
def health():
    return {"status": "Result Service Running"}