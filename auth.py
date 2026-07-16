import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from models import SessionLocal, User
from profile_utils import age_years_from_birth_date

JWT_SECRET = os.getenv("JWT_SECRET", "nutrition-tracker-dev-secret")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 7

RESERVED_USERNAMES = frozenset({"admin"})

security = HTTPBearer(auto_error=False)


def is_username_reserved(username: str) -> bool:
    return username.strip().lower() in RESERVED_USERNAMES


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user: User) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _user_from_token(raw_token: str, db: Session) -> User:
    try:
        payload = decode_access_token(raw_token)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from None

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account deactivated")
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return _user_from_token(credentials.credentials, db)


def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


def get_current_tracker_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin accounts use the admin dashboard only",
        )
    return current_user


def get_current_tracker_user_for_download(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    token: str | None = Query(None, description="JWT token for browser file downloads"),
    db: Session = Depends(get_db),
) -> User:
    raw_token = credentials.credentials if credentials else token
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user = _user_from_token(raw_token, db)
    if user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin accounts use the admin dashboard only",
        )
    return user


def get_current_user_for_download(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    token: str | None = Query(None, description="JWT token for browser file downloads"),
    db: Session = Depends(get_db),
) -> User:
    raw_token = credentials.credentials if credentials else token
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return _user_from_token(raw_token, db)


def user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "is_admin": bool(user.is_admin),
        "is_active": bool(user.is_active),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "name": user.name,
        "email": user.email,
        "gender": user.gender,
        "birth_date": user.birth_date.isoformat() if user.birth_date else None,
        "height_cm": user.height_cm,
        "age": age_years_from_birth_date(user.birth_date),
        "weight_kg": user.weight_kg,
        "initial_weight_kg": user.initial_weight_kg,
        "bmr": user.bmr,
        "bmr_explanation": user.bmr_explanation,
        "created_at": user.created_at.isoformat(),
    }
