import os
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt import PyJWTError

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

ALGORITHM    = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24
_PBKDF2_ITERATIONS = 260_000


def get_secret_key(config: dict) -> str:
    return config.get("web", {}).get(
        "secret_key", os.getenv("WEB_SECRET_KEY", "change-me-in-production"))


def hash_password(plain: str) -> str:
    salt   = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", plain.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(plain: str, hashed: str) -> bool:
    try:
        _, iterations, salt, expected = hashed.split("$")
        digest = hashlib.pbkdf2_hmac(
            "sha256", plain.encode("utf-8"),
            bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, AttributeError):
        return False


def create_access_token(data: dict, secret_key: str,
                        expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire    = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, secret_key, algorithm=ALGORITHM)


def decode_token(token: str, secret_key: str) -> dict:
    try:
        return jwt.decode(token, secret_key, algorithms=[ALGORITHM])
    except PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
