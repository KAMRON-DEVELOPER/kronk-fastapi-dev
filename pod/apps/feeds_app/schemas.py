from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from utility.my_enums import FeedVisibility, CommentPolicy


class AuthorSchema(BaseModel):
    id: UUID
    name: Optional[str]
    username: str
    avatar_url: Optional[str]

    class Config:
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


class CategorySchema(BaseModel):
    name: str


class TagSchema(BaseModel):
    name: str


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
    category: Optional[CategorySchema] = None
    tags: list[TagSchema] = []
    engagement: Optional[EngagementSchema] = None


class FeedResponseSchema(BaseModel):
    feeds: list[FeedSchema]
    end: int
