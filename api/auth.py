"""Authentication: password hashing, JWT issue/verify, and FastAPI deps.

Uses ``bcrypt`` directly (passlib is incompatible with bcrypt 4.x/5.x) and
``PyJWT`` for HS256 tokens (pure-Python HMAC signing — no heavy crypto backend).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .config import settings
from .db import get_db

logger = logging.getLogger("geo_audit.api.auth")

# Used only when JWT_SECRET_KEY is unset (local dev). Never use in production.
# Kept >= 32 bytes so PyJWT doesn't warn about weak HMAC keys.
_DEV_SECRET = "dev-insecure-secret-change-me-in-production-0123456789"

# bcrypt only considers the first 72 bytes of the password.
_BCRYPT_MAX = 72

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def _secret() -> str:
    if settings.jwt_secret_key:
        return settings.jwt_secret_key
    logger.warning(
        "JWT_SECRET_KEY is not set — using an insecure dev secret. "
        "Set JWT_SECRET_KEY in production."
    )
    return _DEV_SECRET


# --- Passwords ------------------------------------------------------------ #


def hash_password(password: str) -> str:
    digest = bcrypt.hashpw(password.encode("utf-8")[:_BCRYPT_MAX], bcrypt.gensalt())
    return digest.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8")[:_BCRYPT_MAX], password_hash.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


# --- Tokens --------------------------------------------------------------- #


def create_access_token(subject: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, _secret(), algorithm=settings.jwt_algorithm)


# --- Dependencies --------------------------------------------------------- #


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> models.User:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, _secret(), algorithms=[settings.jwt_algorithm])
        user_id = payload.get("sub")
    except jwt.InvalidTokenError:
        raise cred_exc
    if not user_id:
        raise cred_exc

    user = db.get(models.User, user_id)
    if user is None or not user.is_active:
        raise cred_exc
    return user


def require_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required"
        )
    return user


# --- Helpers / bootstrap -------------------------------------------------- #


def get_user_by_email(db: Session, email: str) -> Optional[models.User]:
    return db.scalar(select(models.User).where(models.User.email == email))


def ensure_admin(db: Session) -> None:
    """Create the bootstrap admin from env if configured and not yet present."""
    if not settings.admin_email or not settings.admin_password:
        return
    if get_user_by_email(db, settings.admin_email) is not None:
        return
    admin = models.User(
        email=settings.admin_email,
        password_hash=hash_password(settings.admin_password),
        role="admin",
    )
    db.add(admin)
    db.commit()
    logger.info("Bootstrapped admin user %s", settings.admin_email)
