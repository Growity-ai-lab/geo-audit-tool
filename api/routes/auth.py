"""Authentication endpoints: login, current user, and admin-only invites.

Account model is *admin-seeded + admin-invite*: a bootstrap admin is created
from env on startup (see api.auth.ensure_admin), and only admins can create
further users. There is no open self-registration.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth, models
from ..db import get_db
from ..schemas import Token, UserCreate, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(
    form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
) -> Token:
    # OAuth2 form uses "username"; we treat it as the email.
    user = auth.get_user_by_email(db, form.username)
    if (
        user is None
        or not user.is_active
        or not auth.verify_password(form.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=auth.create_access_token(user.id))


@router.get("/me", response_model=UserOut)
def me(current_user: models.User = Depends(auth.get_current_user)) -> models.User:
    return current_user


@router.post(
    "/users", response_model=UserOut, status_code=status.HTTP_201_CREATED
)
def create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_admin),
) -> models.User:
    if auth.get_user_by_email(db, data.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )
    user = models.User(
        email=data.email,
        password_hash=auth.hash_password(data.password),
        role=data.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/users", response_model=List[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_admin),
) -> List[models.User]:
    return list(
        db.scalars(select(models.User).order_by(models.User.created_at.desc()))
    )
