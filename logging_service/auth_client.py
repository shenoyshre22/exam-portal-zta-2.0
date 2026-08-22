import os
import requests
from fastapi import HTTPException, Header

INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "internal-service-token")
LOGIN_SERVICE_URL = os.getenv("LOGIN_SERVICE_URL", "http://login_service:5000")


def verify_token(token: str):
    if token == INTERNAL_SERVICE_TOKEN:
        return {"username": "internal", "role": "teacher"}

    try:
        response = requests.get(
            f"{LOGIN_SERVICE_URL}/verify-token",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Login service unavailable")

    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid token")

    return response.json()


def get_curr_user(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ", 1)[1].strip()
    return verify_token(token)


def get_curr_teacher(authorization: str = Header(default="")):
    user = get_curr_user(authorization)
    if user.get("role") != "teacher":
        raise HTTPException(status_code=403, detail="Teachers only")
    return user
