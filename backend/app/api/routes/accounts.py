"""Template authentication and account management, adapted for managed accounts."""
import uuid
from datetime import timedelta
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import ConfigDict
from sqlmodel import select, func
from sqlalchemy.exc import IntegrityError
from app import crud
from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.core import security
from app.core.config import settings
from app.models import User, UserPublic, UsersPublic, UserCreate, UserUpdate, UserUpdateMe, UpdatePassword, Token
from app.permissions import account_permissions, set_account_permissions

router = APIRouter(tags=["accounts"])
Admin = Annotated[User, Depends(get_current_active_superuser)]

class SafeCreate(UserCreate):
    model_config = ConfigDict(extra="forbid")
class SafeUpdate(UserUpdate):
    model_config = ConfigDict(extra="forbid")
class SafeMe(UserUpdateMe):
    model_config = ConfigDict(extra="forbid")

def user_public(session, user):
    return UserPublic.model_validate(user).model_copy(update={'permissions': account_permissions(session, user)})

@router.post("/login/access-token", response_model=Token)
def login(session: SessionDep, form: Annotated[OAuth2PasswordRequestForm, Depends()]):
    user = crud.authenticate(session=session, email=form.username.strip().lower(), password=form.password)
    if not user or not user.is_active:
        raise HTTPException(401, "邮箱或密码错误，或账号已停用")
    return Token(access_token=security.create_access_token(user.id, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), user.hashed_password))

@router.get("/users/me", response_model=UserPublic)
def me(current_user: CurrentUser, session: SessionDep):
    return user_public(session, current_user)

@router.patch("/users/me", response_model=UserPublic)
def update_me(body: SafeMe, session: SessionDep, current_user: CurrentUser):
    values = body.model_dump(exclude_unset=True)
    if any(v is None for v in values.values()):
        raise HTTPException(422, "字段不能为 null")
    if "email" in values:
        values["email"] = values["email"].lower()
        existing = crud.get_user_by_email(session=session, email=values["email"])
        if existing and existing.id != current_user.id:
            raise HTTPException(409, "邮箱已存在")
    current_user.sqlmodel_update(values)
    session.add(current_user)
    session.commit()
    return user_public(session, current_user)

@router.patch("/users/me/password")
def password(body: UpdatePassword, session: SessionDep, current_user: CurrentUser):
    if not security.verify_password(body.current_password, current_user.hashed_password)[0]:
        raise HTTPException(400, "原密码不正确")
    current_user.hashed_password = security.get_password_hash(body.new_password)
    session.add(current_user)
    session.commit()
    return {"message": "密码已修改"}

@router.get("/users/", response_model=UsersPublic)
def users(session: SessionDep, admin: Admin):
    data = session.exec(select(User).order_by(User.created_at.desc())).all()
    return UsersPublic(data=[user_public(session, u) for u in data], count=len(data))

@router.post("/users/", response_model=UserPublic)
def create(body: SafeCreate, session: SessionDep, admin: Admin):
    body.email = body.email.lower()
    if crud.get_user_by_email(session=session, email=body.email):
        raise HTTPException(409, "邮箱已存在")
    try:
        user = crud.create_user(session=session, user_create=body, commit=False)
        set_account_permissions(session, user, body.permissions)
        session.commit()
        return user_public(session, user)
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "邮箱已存在")

@router.patch("/users/{user_id}", response_model=UserPublic)
def update(user_id: uuid.UUID, body: SafeUpdate, session: SessionDep, admin: Admin):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(404, "账号不存在")
    changes = body.model_dump(exclude_unset=True)
    if any(v is None for v in changes.values()):
        raise HTTPException(422, "字段不能为 null")
    if user.id == admin.id and (changes.get("is_active") is False or changes.get("is_superuser") is False):
        raise HTTPException(400, "不能停用或降级当前管理员")
    if body.email:
        body.email = body.email.lower()
        existing = crud.get_user_by_email(session=session, email=body.email)
        if existing and existing.id != user.id:
            raise HTTPException(409, "邮箱已存在")
    try:
        updated = crud.update_user(session=session, db_user=user, user_in=body, commit=False)
        if body.permissions is not None:
            set_account_permissions(session, updated, body.permissions)
        session.commit()
        return user_public(session, updated)
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "邮箱已存在")
