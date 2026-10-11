from datetime import UTC, datetime, timedelta
from typing import Any
import hashlib
import hmac

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import settings

password_hash = PasswordHash(
    (
        Argon2Hasher(),
        BcryptHasher(),
    )
)


ALGORITHM = "HS256"


def credential_stamp(hashed_password: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), hashed_password.encode(), hashlib.sha256).hexdigest()


def create_access_token(subject: str | Any, expires_delta: timedelta, hashed_password: str = "") -> str:
    expire = datetime.now(UTC) + expires_delta
    to_encode = {"exp": expire, "sub": str(subject), "credential": credential_stamp(hashed_password)}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_password(
    plain_password: str, hashed_password: str
) -> tuple[bool, str | None]:
    return password_hash.verify_and_update(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return password_hash.hash(password)
