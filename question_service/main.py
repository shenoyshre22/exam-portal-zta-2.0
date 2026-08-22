from logger import log_event
from sqlalchemy.orm import Session
import os
import shutil
from database import SessionLocal, engine
import models,schemas
from pdf_parser import get_from_pdf
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Header
from auth_client import verify_token, INTERNAL_SERVICE_TOKEN

models.Base.metadata.create_all(bind=engine)
app=FastAPI(title="Question Service")

#connection to DB

def get_db():
    db=SessionLocal()
    try:
        yield db
    finally:
        db.close()

#check authorization

def get_curr_teacher(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ", 1)[1].strip()
    user = verify_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    if user.get("role") != "teacher":
        raise HTTPException(status_code=403, detail="Teachers only")
    return user
def get_curr_user(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ", 1)[1].strip()
    user = verify_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user

@app.post("/upload-pdf")
def uploading_pdf(exam_id: int, file: UploadFile = File(), db: Session = Depends(get_db), user=Depends(get_curr_teacher)):
    filepath = f"temp_{file.filename}"
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    questions = get_from_pdf(filepath)
    if os.path.exists(filepath):
        os.remove(filepath)
    for qs in questions:
        db.add(models.Question(exam_id=exam_id, question_type="THEORY", question_text=qs))
    db.commit()
    log_event(user["username"], "question", "PDF_UPLOADED", f"{len(questions)} questions added for exam {exam_id}")
    return {"questions_added": len(questions)}


#mcq upload

@app.post("/add-mcq")
def add_mcqs(mcq: schemas.MCQCreation, db: Session = Depends(get_db), user=Depends(get_curr_teacher)):
    new = models.Question(
        exam_id=mcq.exam_id, question_type="MCQ", question_text=mcq.question_text,
        option_a=mcq.option_a, option_b=mcq.option_b, option_c=mcq.option_c,
        option_d=mcq.option_d, correct_answer=mcq.correct_answer
    )
    db.add(new)
    db.commit()
    db.refresh(new)
    log_event(user["username"], "question", "MCQ_ADDED", f"MCQ added for exam {mcq.exam_id}")
    return new

@app.get("/questions/{exam_id}")
def get_questions(exam_id: int, db: Session = Depends(get_db), user=Depends(get_curr_user)):
    return db.query(models.Question).filter(
        models.Question.exam_id == exam_id
    ).all()

@app.get("/")
def home():
    return {"message":"Question Service is Running yay"}


@app.get("/health")
def health():
    return {"status": "Question Service Running"}
