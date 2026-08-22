#importing fastAPI (framework that helps build APIs) and hhtp exception to send proper error responses
from logger import log_event #importing the logging function to log events in the logging service
from fastapi import FastAPI, HTTPException, Header
from models import LoginRequest, SignupRequest  #importing the data models we defined for login and signup
from auth import authenticate_user, create_user, create_access_token, verify_token #importing the auth+ user creation login
from database import create_users_table , get_db_connection #importing database setup functions
from passlib.context import CryptContext #for hashing passwords

#creating FastAPI instance
app = FastAPI()
#setup password hashing context--> to hash passwords before storing them
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
#the bootstrap program for the server
@app.on_event("startup")  #on_event is an older way
def startup():
    create_users_table() #this will create the users table in the database when the server starts up, if not already present
    conn=get_db_connection() #connect to the database
    #this is for our testing and demo purpose 
    users= [
        ("teacher1", pwd_context.hash("password1"), "teacher"),
        ("student1", pwd_context.hash("password2"), "student")
    ]
    #insert users into the database
    for user in users:
        try:
            conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", user)
        except Exception:
            #if user already exists , ignore the error
            pass
        #save changes and close the database connection
    conn.commit()
    conn.close()
@app.get("/")
def home():
        return{"message": "Login Service Running yay"}  # just to test for our sake , if the service runs

    #---signup API to create a new user--- 
@app.post("/signup")
def signup(data: SignupRequest):
    if data.role not in ["student", "teacher"]:
        raise HTTPException(status_code=400, detail="Role must be either 'student' or 'teacher'")
    success = create_user(data.username, data.password, data.role)
    if not success:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    # NEW
    log_event(data.username, "login", "SIGNUP", f"New {data.role} account created")
    return {"message": "User created successfully"}

    
#-- login API (to authenticate existing user and return their role)---
@app.post("/login")
def login(data: LoginRequest):
    user = authenticate_user(data.username, data.password)
    if not user:
        # NEW — log failed attempt
        log_event(data.username, "login", "LOGIN_FAILED", "Invalid username or password")
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    token = create_access_token({"sub": user["username"], "role": user["role"]})
    
    # NEW — log success
    log_event(data.username, "login", "LOGIN_SUCCESS", f"User logged in as {user['role']}")
    return {"message": "Login successful", "role": user["role"], "access_token": token, "token_type": "bearer"}

@app.get("/verify-token")
def verify_user_token(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.split(" ", 1)[1].strip()
    user = verify_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return {"username": user["username"], "role": user["role"]}