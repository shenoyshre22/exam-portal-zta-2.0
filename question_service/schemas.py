from pydantic import BaseModel

class MCQCreation(BaseModel):
    exam_id: int
    question_text:str
    option_a:str
    option_b:str
    option_c:str
    option_d:str
    correct_answer:str