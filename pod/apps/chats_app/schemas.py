from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class CreateMessageSchema(BaseModel):
    message: str
    # image_urls: Optional[list[str]] = None
    # video_urls: Optional[list[str]] = None


class ParticipantSchema(BaseModel):
    id: UUID
    name: str
    username: str
    avatar_url: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    is_online: bool = False

    class Config:
        from_attributes = True
        json_encoders = {UUID: lambda v: v.hex, datetime: lambda v: int(v.timestamp()) if v is not None else None}


class ChatSchema(BaseModel):
    id: UUID
    participant: ParticipantSchema
    last_message: Optional[str]
    last_activity_at: datetime

    # last_message_seen: Optional[bool]
    # unread_count: int

    class Config:
        from_attributes = True
        json_encoders = {UUID: lambda v: v.hex, datetime: lambda v: int(v.timestamp())}


class ChatResponseSchema(BaseModel):
    chats: list[ChatSchema]
    end: int


class ChatMessageSchema(BaseModel):
    id: UUID
    sender_id: UUID
    chat_id: UUID
    message: str
    # image_urls: Optional[list[str]] = None
    # video_urls: Optional[list[str]] = None
    created_at: datetime

    # scheduled_at: Optional[datetime] = None
    # read_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        json_encoders = {UUID: lambda v: v.hex, datetime: lambda v: int(v.timestamp())}


class ChatMessageResponseSchema(BaseModel):
    messages: list[ChatMessageSchema]
    end: int

    class Config:
        from_attributes = True
        json_encoders = {UUID: lambda v: v.hex, datetime: lambda v: int(v.timestamp())}
