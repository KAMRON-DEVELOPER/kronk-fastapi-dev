from datetime import UTC, datetime, timedelta
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator
from settings.my_exceptions import ValidationException
from utility.my_enums import CommentMode, FeedVisibility
from utility.my_logger import my_logger


class FeedCreateSchema(BaseModel):
    body: Optional[str] = None
    scheduled_time: Optional[datetime] = None
    tags: Optional[list[UUID]] = None
    category: Optional[UUID] = None

    class Config:
        from_attributes = True

    @field_validator("body")
    def validate_body(cls, value: Optional[str]):
        if value is None:
            raise ValidationException("body is required.")
        if len(value) > 200:
            raise ValidationException("body is exceeded max 200 character limit.")
        return value

    @field_validator("scheduled_time")
    def validate_scheduled(cls, value: Optional[datetime]):
        try:
            if value is not None:
                my_logger.debug(f"scheduled_time field_validator: {value}, type: {type(value)}")
                now = datetime.now(UTC)
                max_future = now + timedelta(days=7)

                if value < now:
                    raise ValidationException("Scheduled time cannot be in the past.")

                if value > max_future:
                    raise ValidationException("Scheduled time cannot be more than 7 days in the future.")
        except Exception as exception:
            my_logger.error(f"Error while validating feed schedule time. detail: {exception}")
            raise ValidationException(f"{exception}")
        return value


class DummySchema1(BaseModel):
    feed_body: Optional[str] = None

    @field_validator("feed_body")
    def validate_body(cls, value: Optional[str]) -> None:
        if value is None:
            raise ValueError("body is required.")
        if len(value) > 200:
            raise ValueError("body is exceeded max 200 character limit.")


class DummySchema(BaseModel):
    feed_body: Optional[str] = None
    scheduled_time: Optional[datetime] = None
    tags: Optional[list[UUID]] = None
    category: Optional[UUID] = None
    remove_image_targets: Optional[list[str]] = None
    remove_video_target: Optional[str] = None

    @field_validator("feed_body")
    def validate_body(cls, value: Optional[str]) -> None:
        if value is None:
            raise ValueError("body is required.")
        if len(value) > 200:
            raise ValueError("body is exceeded max 200 character limit.")


class AuthorSchema(BaseModel):
    id: UUID
    first_name: Optional[str]
    last_name: Optional[str]
    username: str
    avatar_url: Optional[str]

    class Config:
        from_attributes = True


class CategorySchema(BaseModel):
    name: str

    class Config:
        from_attributes = True


class TagSchema(BaseModel):
    name: str

    class Config:
        from_attributes = True


class FeedSchema(BaseModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
    author: AuthorSchema
    body: str
    image_urls: Optional[list[str]]
    video_url: Optional[str]
    scheduled_time: Optional[datetime]
    comment_mode: CommentMode
    feed_visibility: FeedVisibility
    tags: list[TagSchema] = []
    category: Optional[CategorySchema]

    class Config:
        from_attributes = True
        json_encoders = {UUID: lambda v: v.hex, datetime: lambda v: v.timestamp() if v is not None else None}
