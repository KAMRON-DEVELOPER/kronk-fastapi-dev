from datetime import UTC, datetime, timedelta
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator

from settings.my_exceptions import ValidationException
from utility.my_enums import FeedVisibility, CommentPolicy
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


class AuthorSchema(BaseModel):
    id: UUID
    name: Optional[str]
    username: str
    avatar_url: Optional[str]

    class Config:
        from_attributes = True
        json_encoders = {UUID: lambda v: v.hex, datetime: lambda v: v.timestamp() if v is not None else None}


class EngagementSchema(BaseModel):
    comments: Optional[int] = None
    reposts: Optional[int] = None
    quotes: Optional[int] = None
    likes: Optional[int] = None
    views: Optional[int] = None
    bookmarks: Optional[int] = None
    reposted: Optional[bool] = None
    quoted: Optional[bool] = None
    liked: Optional[bool] = None
    viewed: Optional[bool] = None
    bookmarked: Optional[bool] = None

    class Config:
        from_attributes = True
        json_encoders = {UUID: lambda v: v.hex, datetime: lambda v: v.timestamp() if v is not None else None}


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
    body: str
    author: AuthorSchema
    video_url: Optional[str] = None
    image_urls: Optional[list[str]] = []
    scheduled_at: Optional[datetime] = None
    feed_visibility: FeedVisibility
    comment_policy: CommentPolicy
    engagement: Optional[EngagementSchema] = None
    tags: list[TagSchema] = []
    category: Optional[CategorySchema] = None

    class Config:
        from_attributes = True
        json_encoders = {UUID: lambda v: v.hex, datetime: lambda v: v.timestamp() if v is not None else None}


class FeedResponseSchema(BaseModel):
    feeds: list[FeedSchema]
    end: int

    class Config:
        from_attributes = True
        json_encoders = {UUID: lambda v: v.hex, datetime: lambda v: v.timestamp() if v is not None else None}
