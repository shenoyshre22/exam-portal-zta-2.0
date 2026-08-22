from logger import log_event
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from database import SessionLocal, engine, Base
from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime , timezone 
from pydantic import BaseModel
from auth_client import get_curr_user

app = FastAPI(title="Submission Service")


# ---------------- DATABASE MODEL ----------------
class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(String)
    exam_id = Column(String)
    question_id = Column(String)
    answer = Column(String)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))


Base.metadata.create_all(bind=engine)


# ---------------- SCHEMA ----------------
class SubmissionCreate(BaseModel):
    student_id: str
    exam_id: str
    question_id: str
    answer: str


# ---------------- DB DEPENDENCY ----------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------- ROUTES ----------------

@app.get("/")
def root():
    return {"message": "Submission Service Running"}


# 🔹 Submit answer
@app.post("/submit-answer")
def submit_answer(data: SubmissionCreate, db: Session = Depends(get_db), user=Depends(get_curr_user)):
    # A student may only submit answers as themselves; teachers/internal calls are exempt.
    if user.get("role") == "student" and user.get("username") != data.student_id:
        raise HTTPException(status_code=403, detail="You can only submit answers as yourself")

    existing = db.query(Submission).filter(
        Submission.student_id == data.student_id,
        Submission.exam_id == data.exam_id,
        Submission.question_id == data.question_id
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Answer already submitted")

    new_submission = Submission(
        student_id=data.student_id,
        exam_id=data.exam_id,
        question_id=data.question_id,
        answer=data.answer
    )
    db.add(new_submission)
    db.commit()
    db.refresh(new_submission)
    log_event(data.student_id, "submission", "ANSWER_SUBMITTED", f"Answer submitted for question {data.question_id} in exam {data.exam_id}")
    return {"message": "Answer submitted", "id": new_submission.id}


# 🔹 Get submissions by student
@app.get("/submissions/{student_id}")
def get_submissions(student_id: str, db: Session = Depends(get_db), user=Depends(get_curr_user)):
    if user.get("role") == "student" and user.get("username") != student_id:
        raise HTTPException(status_code=403, detail="You can only view your own submissions")
    data = db.query(Submission).filter(Submission.student_id == student_id).all()
    return data


# 🔹 Health
@app.get("/health")
def health():
    return {"status": "Submission Service Running"}