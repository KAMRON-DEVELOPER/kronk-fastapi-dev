from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ParticipantSchema(BaseModel):
    id: UUID
    name: str
    username: str
    avatar_url: Optional[str] = None
    is_online: bool = False

    class Config:
        from_attributes = True
        json_encoders = {UUID: lambda v: v.hex, datetime: lambda v: v.timestamp() if v is not None else None}


class ChatTileSchema(BaseModel):
    id: UUID
    participant: ParticipantSchema
    last_activity_at: datetime
    last_message: Optional[str]
    last_message_seen: Optional[bool]
    unread_count: int

    class Config:
        from_attributes = True
        json_encoders = {UUID: lambda v: v.hex, datetime: lambda v: int(v.timestamp())}


class ChatTileResponseSchema(BaseModel):
    chat_tiles: list[ChatTileSchema]
    end: int
