from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ChatTileSchema(BaseModel):
    chat_id: UUID
    user_id: UUID
    username: str
    first_name: Optional[str]
    last_name: Optional[str]
    avatar_url: Optional[str]
    last_activity_at: datetime
    last_message: Optional[str]
    last_message_seen: Optional[bool]
    unread_count: int

    class Config:
        use_enum_values = True
        from_attributes = True
        json_encoders = {UUID: lambda v: v.hex, datetime: lambda v: int(v.timestamp())}
