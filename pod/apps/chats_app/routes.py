from uuid import UUID

from fastapi import APIRouter

from apps.chats_app.models import ChatModel, ChatParticipantModel
from apps.chats_app.schemas import ChatTileSchema
from settings.my_database import DBSession
from settings.my_dependency import jwtDependency
from settings.my_exceptions import ApiException
from utility.my_logger import my_logger
from sqlalchemy import select

chats_router = APIRouter()


@chats_router.get(path="/tiles", response_model=list[ChatTileSchema], status_code=200)
async def get_chats_route(jwt: jwtDependency, session: DBSession):
    try:
        user_id: UUID = jwt.user_id

        # Get all chat IDs where the user participates
        result = await session.execute(select(ChatModel).join(ChatParticipantModel).filter(ChatParticipantModel.user_id == user_id))
        chats = result.scalars().all()

        # my_logger.debug(f"result: {result}")
        my_logger.debug(f"chats: {chats}")

        if not chats:
            return []

        chat_tiles = []

        for chat in chats:
            # Find the other participant
            other_user = next(p.user for p in chat.participants if p.user_id != user_id)
            my_logger.debug(f"other_user: {other_user}")

            # Get the last message in chat
            last_message = max(chat.chat_messages, key=lambda m: m.created_at, default=None)
            my_logger.debug(f"last_message: {last_message}")

            # Determine if it's seen
            last_message_seen = False
            unread_count = 0

            if last_message:
                if last_message.sender_id == user_id:
                    last_message_seen = last_message.read_at is not None
                else:
                    # Count unread messages from other_user
                    unread_count = sum(1 for m in chat.chat_messages if m.sender_id == other_user.id and m.read_at is None)

            chat_tiles.append(
                ChatTileSchema(
                    chat_id=chat.id,
                    user_id=other_user.id,
                    username=other_user.username,
                    first_name=other_user.first_name,
                    last_name=other_user.last_name,
                    avatar_url=None,
                    last_activity_at=chat.last_message_at or chat.created_at,
                    last_message=last_message.message if last_message else None,
                    last_message_seen=last_message_seen,
                    unread_count=unread_count
                )
            )

        return chat_tiles

    except Exception as e:
        my_logger.exception(f"Exception e: {e}")
        raise ApiException(status_code=400, detail=f"Something went wrong while getting chat tiles, e: {e}")
