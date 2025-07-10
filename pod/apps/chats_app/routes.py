from datetime import datetime, UTC
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter
from sqlalchemy import select, exists, func
from sqlalchemy.orm import selectinload

from apps.chats_app.models import ChatModel, ChatMessageModel, ChatParticipantModel
from apps.chats_app.schemas import ChatResponseSchema, CreateMessageSchema, ChatSchema, ParticipantSchema, ChatMessageResponseSchema, ChatMessageSchema
from apps.users_app.schemas import ResultSchema
from settings.my_database import DBSession
from settings.my_dependency import strictJwtDependency
from settings.my_exceptions import ApiException
from settings.my_redis import chat_cache_manager, cache_manager, pubsub_manager
from utility.my_enums import ChatEvent
from utility.my_logger import my_logger

chats_router = APIRouter()

'''
class MessageBaseModel(BaseModel):
    __abstract__ = True
    sender_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(column="user_table.id", ondelete="CASCADE"))
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_urls: Mapped[Optional[list[str]]] = mapped_column(ARRAY(item_type=String), nullable=True)
    video_urls: Mapped[Optional[list[str]]] = mapped_column(ARRAY(item_type=String), nullable=True)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

class ChatParticipantModel(BaseModel):
    __tablename__ = "chat_participant_table"
    __table_args__ = (UniqueConstraint("user_id", "chat_id", name="uq_user_chat"),)
    background_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(column="user_table.id", ondelete="CASCADE"), primary_key=True)
    chat_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(column="chat_table.id", ondelete="CASCADE"), primary_key=True)
    user: Mapped["UserModel"] = relationship(argument="UserModel", back_populates="chat_participants")
    chat: Mapped["ChatModel"] = relationship(argument="ChatModel", back_populates="chat_participants")


class ChatModel(BaseModel):
    __tablename__ = "chat_table"
    last_message_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    chat_participants: Mapped[list["ChatParticipantModel"]] = relationship(argument="ChatParticipantModel", back_populates="chat", cascade="all, delete-orphan")
    chat_messages: Mapped[list["ChatMessageModel"]] = relationship(argument="ChatMessageModel", back_populates="chat", cascade="all, delete-orphan")
    users: Mapped[list["UserModel"]] = relationship(secondary="chat_participant_table", back_populates="chats", viewonly=True)


class ChatMessageModel(MessageBaseModel):
    __tablename__ = "chat_message_table"
    chat_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey(column="chat_table.id", ondelete="CASCADE"))
    chat: Mapped["ChatModel"] = relationship(argument="ChatModel", back_populates="chat_messages", passive_deletes=True)
    sender: Mapped["UserModel"] = relationship(argument="UserModel", back_populates="chat_messages", passive_deletes=True)

'''

'''

class ParticipantSchema(BaseModel):
    id: UUID
    name: str
    username: str
    avatar_url: Optional[str] = None
    last_seen_at: datetime
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

'''


@chats_router.post(path="/create", response_model=ChatSchema, status_code=200)
async def create_chat_tile_route(jwt: strictJwtDependency, session: DBSession, schema: CreateMessageSchema, participant_id: UUID):
    try:
        if jwt.user_id == participant_id:
            raise ApiException(status_code=400, detail="Cannot create chat with self")

        exists_stmt = (
            select(ChatParticipantModel.chat_id)
            .where(ChatParticipantModel.user_id.in_([jwt.user_id, participant_id]))
            .group_by(ChatParticipantModel.chat_id)
            .having(func.count() > 1)
        )
        is_chat_exist = await session.scalar(select(exists(exists_stmt)))
        if is_chat_exist:
            raise ApiException(status_code=403, detail="Chat already exist.")

        chat_id = uuid4()
        now = datetime.now(UTC)

        chat = ChatModel(id=chat_id, last_message_at=now)
        sender = ChatParticipantModel(chat_id=chat_id, user_id=jwt.user_id)
        receiver = ChatParticipantModel(chat_id=chat_id, user_id=participant_id)
        message = ChatMessageModel(chat_id=chat_id, sender_id=jwt.user_id, message=schema.message)

        session.add_all([chat, sender, receiver, message])
        await session.commit()

        participant_profile = await cache_manager.get_profile(participant_id.hex)
        if not participant_profile:
            raise ApiException(400, "Participant profile not found")

        mapping = {"id": chat_id.hex, "last_activity_at": int(now.timestamp()), "last_message": schema.message}
        await chat_cache_manager.create_chat(user_id=jwt.user_id.hex, participant_id=participant_id.hex, chat_id=chat_id.hex, mapping=mapping)

        is_online = await chat_cache_manager.is_online(participant_id=participant_id.hex)

        response = ChatSchema(
            id=chat_id,
            participant=ParticipantSchema(
                id=participant_id,
                name=participant_profile.get("name"),
                username=participant_profile.get("username"),
                avatar_url=participant_profile.get("avatar_url"),
                last_seen_at=datetime.fromtimestamp(int(participant_profile.get("last_seen_at"))) if "last_seen_at" in participant_profile else None,
                is_online=is_online
            ),
            last_activity_at=now,
            last_message=schema.message
        )

        if is_online:
            participant_profile = await cache_manager.get_profile(jwt.user_id.hex)

            data = {
                "type": ChatEvent.created_chat.value,
                "id": chat_id.hex,
                "participant": {
                    "id": jwt.user_id.hex,
                    "name": participant_profile.get("name"),
                    "username": participant_profile.get("username"),
                    "avatar_url": participant_profile.get("avatar_url"),
                    "last_seen_at": now.timestamp(),
                    "is_online": True,
                },
                "last_activity_at": int(now.timestamp()),
                "last_message": schema.message
            }
            await pubsub_manager.publish(topic=f"chats:home:{participant_id.hex}", data=data)

        return response
    except Exception as e:
        my_logger.exception(f"Exception e: {e}")
        raise ApiException(status_code=500, detail=f"Something went wrong while creating chat: {e}")


@chats_router.post(path="/delete", response_model=ResultSchema, status_code=200)
async def delete_chat_tile_route(jwt: strictJwtDependency, session: DBSession, chat_id: UUID):
    try:
        is_user_chat_owner: bool = await chat_cache_manager.is_user_chat_owner(user_id=jwt.user_id.hex, chat_id=chat_id.hex)
        if not is_user_chat_owner:
            raise ApiException(status_code=403, detail="Chat does not belong to you")

        stmt = select(ChatModel).options(selectinload(ChatModel.chat_participants)).where(ChatModel.id == chat_id)
        result = await session.execute(stmt)
        chat: Optional[ChatModel] = result.scalar_one_or_none()
        if not chat:
            return {"ok": False}

        await chat_cache_manager.delete_chat(participants=[pid.user_id.hex for pid in chat.chat_participants], chat_id=chat_id.hex)
        await session.delete(instance=chat)
        await session.commit()

        return {"ok": True}
    except Exception as e:
        my_logger.exception(f"Exception e: {e}")
        raise ApiException(status_code=400, detail=f"Something went wrong while getting chat tiles, e: {e}")


@chats_router.get(path="", response_model=ChatResponseSchema, status_code=200)
async def get_chats_route(jwt: strictJwtDependency, start: int = 0, end: int = 20):
    try:
        response: ChatResponseSchema = await chat_cache_manager.get_chats(user_id=jwt.user_id.hex, start=start, end=end)
        my_logger.debug(f"length of response.chats: {len(response.chats)}, response.end: {response.end}")
        return response
    except Exception as e:
        my_logger.exception(f"Exception e: {e}")
        raise ApiException(status_code=400, detail=f"Something went wrong while getting chat tiles, e: {e}")


@chats_router.get(path="/messages", response_model=ChatMessageResponseSchema, status_code=200)
async def get_chats_route(jwt: strictJwtDependency, session: DBSession, chat_id: UUID, start: int = 0, end: int = 20):
    try:
        my_logger.warning("1")
        count_stmt = select(func.count()).where(ChatMessageModel.chat_id == chat_id)
        count_result = await session.execute(count_stmt)
        total_messages = count_result.scalar_one()

        my_logger.warning("2")
        if total_messages:
            return {"messages": [], "end": 0}

        my_logger.warning("3")

        stmt = (select(ChatMessageModel).where(ChatMessageModel.chat_id == chat_id).order_by(ChatMessageModel.created_at.desc()).offset(start).limit(end - start))
        result = await session.scalars(stmt)
        messages: list[ChatMessageModel] = result.all()
        my_logger.warning("4")

        response = ChatMessageResponseSchema(messages=[ChatMessageSchema.model_validate(obj=message) for message in messages], end=total_messages - 1)
        my_logger.warning("5")
        return response
    except Exception as e:
        my_logger.exception(f"Exception e: {e}")
        raise ApiException(status_code=400, detail=f"Something went wrong while getting chat tiles, e: {e}")
