from logger import log_event
from fastapi import FastAPI, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String, Float, text
from database import SessionLocal, engine, Base
from auth_client import verify_token

app = FastAPI(title="Exam Service")


class Exam(Base):
    __tablename__ = "exams"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    total_marks = Column(Integer, nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="active")
    target_students = Column(Integer, nullable=False, default=0)
    average_score = Column(Float, nullable=False, default=0.0)


Base.metadata.create_all(bind=engine)


def ensure_exam_schema():
    # Backward-safe migration for existing SQLite table.
    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(exams)"))}

        if "status" not in columns:
            conn.execute(text("ALTER TABLE exams ADD COLUMN status VARCHAR DEFAULT 'active'"))
        if "target_students" not in columns:
            conn.execute(text("ALTER TABLE exams ADD COLUMN target_students INTEGER DEFAULT 0"))
        if "average_score" not in columns:
            conn.execute(text("ALTER TABLE exams ADD COLUMN average_score FLOAT DEFAULT 0"))

        conn.commit()


ensure_exam_schema()


class ExamCreate(BaseModel):
    title: str
    description: str = ""
    total_marks: int
    duration_minutes: int
    status: str = "active"
    target_students: int = 0
    average_score: float = 0.0


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

#to grant access only to teachers for certain endpoints
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


# to grant access to any logged in user
def get_curr_user(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ", 1)[1].strip()
    user = verify_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user


@app.get("/")
def root():
    return {"message": "Exam Service Running"}

@app.post("/exams")
def create_exam(payload: ExamCreate, db: Session = Depends(get_db), user=Depends(get_curr_teacher)):
    normalized_status = payload.status.lower().strip()
    if normalized_status not in {"active", "pending", "closed"}:
        raise HTTPException(status_code=400, detail="status must be one of active, pending, closed")

    exam = Exam(
        title=payload.title,
        description=payload.description,
        total_marks=payload.total_marks,
        duration_minutes=payload.duration_minutes,
        status=normalized_status,
        target_students=max(int(payload.target_students), 0),
        average_score=float(payload.average_score),
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)
    log_event(user["username"], "exam", "EXAM_CREATED", f"Exam '{payload.title}' created with id {exam.id}")
    return exam

@app.get("/exams")
def list_exams(db: Session = Depends(get_db), user=Depends(get_curr_user)):
    return db.query(Exam).all()


@app.get("/exams/{exam_id}")
def get_exam(exam_id: int, db: Session = Depends(get_db), user=Depends(get_curr_user)):
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    return exam


@app.get("/health")
def health():
    return {"status": "Exam Service Running"}
