"""Pydantic schemas for users."""

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from ..models import User


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class StartDateUpdate(BaseModel):
    # `dt.date` (not `date`) so the field name cannot shadow the type.
    start_date: dt.date


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str | None = None
    start_date: dt.date
    has_password: bool

    @classmethod
    def from_user(cls, user: User) -> "UserOut":
        return cls(
            id=user.id,
            email=user.email,
            name=user.name,
            start_date=user.start_date,
            has_password=user.password_hash is not None,
        )
