from database import get_db_connection #to connect to our database
from passlib.context import CryptContext #this inbuilt library will help us hash out passwords
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
import os
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto") #this is the setup that will help us hash and verify passwords
#the algorithm bcrpyt which is a hashing algorithm used in real systems
SECRET_KEY = os.getenv("SECRET_KEY", "exam-portal-secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120


#---function to check if the entered password matches the stored password-----
def verify_password(plain_password,hashed_password):
    #hashed password is the one stored in the database and plain password is the one entered by the user
    return pwd_context.verify(plain_password, hashed_password) #verify will help comparing safely
 
 #---function to fetch a user from the database---
def get_user(username: str):
    conn = get_db_connection() #open and connect to the database 
    #sql query
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone() #fetch the user with the given username
    conn.close() #close the connection
    return user #return the user data

#---function to handle login logic ---
def authenticate_user(username: str , password: str):
    #checks if user exists and if password is correct
    user=get_user(username) 
    if not user:
        return None
    if not verify_password(password,user["password"]):
        return None
    return user #if both checks pass, then return the user data
#---function to create a new user in the database---
def create_user(username: str, password: str, role: str):
    conn = get_db_connection()

    # hash password before storing
    hashed_password = pwd_context.hash(password)

    try:
        conn.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            (username, hashed_password, role)
        )
        conn.commit()
    except Exception:
        conn.close()
        return False  # user already exists

    conn.close()
    return True


def create_access_token(data: dict, expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES):
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload.update({"exp": expire})
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        role = payload.get("role")
        if not username or not role:
            return None
        return {"username": username, "role": role}
    except JWTError:
        return None