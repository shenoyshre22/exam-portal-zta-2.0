from pydantic import BaseModel

# this defines what data your API expects for login
class LoginRequest(BaseModel):
    username: str   # to declare that itmust be a string
    password: str   # must be a string
    #using fast api here to check input format and throw error if theres any missing fields
# for signup request
class SignupRequest(BaseModel):
    username: str
    password: str
    role: str   # student or teacher   