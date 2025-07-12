from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class CreateMessageSchema(BaseModel):
    message: str


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


class ChatMessageSchema(BaseModel):
    id: UUID
    sender_id: UUID
    chat_id: UUID
    message: str
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {UUID: lambda v: v.hex, datetime: lambda v: int(v.timestamp())}


class ChatSchema(BaseModel):
    id: UUID
    participant: ParticipantSchema
    last_message: Optional[ChatMessageSchema] = None
    last_activity_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {UUID: lambda v: v.hex, datetime: lambda v: int(v.timestamp())}


class ChatResponseSchema(BaseModel):
    chats: list[ChatSchema]
    end: int


class ChatMessageResponseSchema(BaseModel):
    messages: list[ChatMessageSchema]
    end: int

    class Config:
        from_attributes = True
        json_encoders = {UUID: lambda v: v.hex, datetime: lambda v: int(v.timestamp())}
