from sqlalchemy import Column, Integer,String, Text
from database import Base

class Question(Base):
    __tablename__="questions"

    id=Column(Integer, primary_key=True,index=True)
    exam_id=Column(Integer)
    question_type=Column(String)
    question_text=Column(Text)
    
    #mcqs

    option_a=Column(String, nullable=True)
    option_b=Column(String, nullable=True)
    option_c=Column(String, nullable=True)
    option_d=Column(String,nullable=True)
    correct_answer=Column(String, nullable=True)