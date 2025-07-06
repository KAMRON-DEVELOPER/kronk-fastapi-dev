import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator

from settings.my_exceptions import ValidationException
from utility.my_enums import FollowPolicy, UserRole, UserStatus
from utility.validators import validate_email, validate_length, validate_password, validate_username, violent_words_regex


class RegisterSchema(BaseModel):
    name: str
    username: str
    email: str
    password: str

    @field_validator("name")
    def validate_name(cls, value: str):
        validate_length(field=value, min_len=2, max_len=30, field_name="Name")
        return value

    @field_validator("username")
    def validate_code(cls, value: str):
        validate_username(username=value)
        return value

    @field_validator("email")
    def validate_email(cls, value: str):
        validate_email(email=value)
        return value

    @field_validator("password")
    def validate_password(cls, value: str):
        validate_password(password_string=value)
        return value


class VerifySchema(BaseModel):
    code: str

    @field_validator("code")
    def validate_code(cls, value: str):
        if not value.isdigit():
            raise ValueError("Code must contain only digits.")
        if len(value) != 4:
            raise ValueError("Code must be 4 digit long.")
        return value


class LoginSchema(BaseModel):
    username: str
    password: str

    @field_validator("username")
    def validate_code(cls, value: str):
        validate_username(username=value)
        return value

    @field_validator("password")
    def validate_password(cls, value: str):
        validate_password(password_string=value)
        return value


class RequestForgotPasswordSchema(BaseModel):
    email: str

    @field_validator("email")
    def validate_email(cls, value: str):
        validate_email(email=value)
        return value


class ResetPasswordSchema(BaseModel):
    code: str
    new_password: str

    @field_validator("code")
    def validate_code(cls, value: str):
        if not value.isdigit():
            raise ValueError("Code must contain only digits.")
        if len(value) != 4:
            raise ValueError("Code must be 4 digit long.")
        return value

    @field_validator("new_password")
    def validate_new_password(cls, value: Optional[str]):
        validate_password(password_string=value)
        return value


class ProfileSchema(BaseModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
    name: Optional[str] = None
    username: str
    email: str
    password: str
    avatar_url: Optional[str] = None
    banner_url: Optional[str] = None
    banner_color: Optional[str] = None
    birthdate: Optional[datetime] = None
    bio: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    role: UserRole
    status: UserStatus
    follow_policy: FollowPolicy
    followers_count: int
    followings_count: int

    class Config:
        from_attributes = True
        json_encoders = {UUID: lambda v: v.hex, datetime: lambda v: v.timestamp() if v is not None else None}


class ProfileUpdateSchema(BaseModel):
    name: Optional[str] = None
    username: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    birthdate: Optional[datetime] = None
    bio: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    follow_policy: FollowPolicy = FollowPolicy.auto_accept

    class Config:
        use_enum_values = True
        from_attributes = True
        json_encoders = {UUID: lambda v: v.hex, datetime: lambda v: v.timestamp() if v is not None else None}

    @field_validator("username")
    def validate_username(cls, value: Optional[str]):
        validate_username(username=value)
        return value

    @field_validator("email")
    def validate_email(cls, value: Optional[str]):
        validate_email(email=value)
        return value

    @field_validator("password")
    def validate_password(cls, value: Optional[str]):
        validate_password(password_string=value)
        return value

    @field_validator("name")
    def validate_name(cls, value: Optional[str]):
        if value is not None:
            validate_length(field=value, min_len=2, max_len=30, field_name="Name")
        return value

    @field_validator("birthdate")
    def validate_birthdate(cls, value: Optional[datetime]):
        if value is not None:
            min_age_date = datetime.now(timezone.utc) - timedelta(days=12 * 365)
            max_age_date = datetime.now(timezone.utc) - timedelta(days=100 * 365)
            if not (max_age_date <= value <= min_age_date):
                raise ValidationException(detail="Birthdate must be between 12 and 100 years ago.")
        return value

    @field_validator("bio")
    def validate_bio(cls, value: Optional[str]):
        if value is not None:
            validate_length(field=value, min_len=0, max_len=200, field_name="bio")
            if re.search(violent_words_regex, value, re.IGNORECASE):
                raise ValidationException(detail="Bio contains sensitive or inappropriate content.")
        return value


class RegistrationTokenSchema(BaseModel):
    verify_token: str
    verify_token_expiration_date: str


class ForgotPasswordTokenSchema(BaseModel):
    forgot_password_token: str
    forgot_password_token_expiration_date: str


class TokenSchema(BaseModel):
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None


class ProfileTokenSchema(BaseModel):
    user: ProfileSchema
    tokens: TokenSchema


class ResultSchema(BaseModel):
    ok: bool


class ProfileSearchSchema(ProfileSchema):
    is_following: Optional[bool] = None


class UserSearchResponseSchema(BaseModel):
    users: list[ProfileSearchSchema]
    end: int
