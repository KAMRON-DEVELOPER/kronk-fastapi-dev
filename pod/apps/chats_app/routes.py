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
from utility.my_logger import my_logger

chats_router = APIRouter()


@chats_router.post(path="/messages/create", response_model=ChatSchema, status_code=200)
async def create_chat_route(jwt: strictJwtDependency, session: DBSession, schema: CreateMessageSchema, participant_id: UUID):
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
        message_id = uuid4()
        now = datetime.now(UTC)
        now_timestamp = int(now.timestamp())

        chat = ChatModel(id=chat_id, last_message_at=now)
        sender = ChatParticipantModel(chat_id=chat_id, user_id=jwt.user_id)
        receiver = ChatParticipantModel(chat_id=chat_id, user_id=participant_id)
        message = ChatMessageModel(id=message_id, chat_id=chat_id, sender_id=jwt.user_id, message=schema.message)
        session.add_all([chat, sender, receiver, message])
        await session.commit()

        participant_profile = await cache_manager.get_profile(participant_id.hex)
        if not participant_profile:
            raise ApiException(400, "Participant profile not found")

        mapping = {
            "id": chat_id.hex,
            "last_activity_at": now_timestamp,
            "last_message": {"id": message_id.hex, "chat_id": chat_id.hex, "sender_id": jwt.user_id.hex, "message": schema.message, "created_at": now_timestamp}
        }
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
            last_message=ChatMessageSchema(id=message_id, chat_id=chat_id, sender_id=jwt.user_id, message=schema.message, created_at=now)
        )

        if is_online:
            participant_profile = await cache_manager.get_profile(jwt.user_id.hex)

            data = {
                **mapping,
                "participant": {
                    "id": jwt.user_id.hex,
                    "name": participant_profile.get("name"),
                    "username": participant_profile.get("username"),
                    "avatar_url": participant_profile.get("avatar_url"),
                    "last_seen_at": now_timestamp,
                    "is_online": True,
                }
            }
            await pubsub_manager.publish(topic=f"chats:home:{participant_id.hex}", data=data)

        return response
    except Exception as e:
        my_logger.exception(f"Exception e: {e}")
        raise ApiException(status_code=500, detail=f"Something went wrong while creating chat: {e}")


@chats_router.delete(path="/delete", response_model=ResultSchema, status_code=200)
async def delete_chat_route(jwt: strictJwtDependency, session: DBSession, chat_id: UUID):
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
async def get_chat_messages_route(_: strictJwtDependency, session: DBSession, chat_id: UUID, start: int = 0, end: int = 20):
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


@chats_router.delete(path="/messages/delete", response_model=ResultSchema, status_code=200)
async def delete_chat_message_route(jwt: strictJwtDependency, session: DBSession, _message_id: UUID, chat_id: UUID):
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
