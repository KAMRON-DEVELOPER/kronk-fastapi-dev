import asyncio

from fastapi import APIRouter, WebSocket
from redis.asyncio.client import PubSub

from settings.my_dependency import websocketDependency
from settings.my_redis import pubsub_manager, chat_cache_manager
from settings.my_websocket import chat_ws_manager, WebSocketContextManager
from utility.my_enums import ChatEvent
from utility.my_logger import my_logger

chat_ws_router = APIRouter()


@chat_ws_router.websocket("/home")
async def enter_home(websocket_dependency: websocketDependency):
    user_id: str = websocket_dependency.user_id.hex
    websocket: WebSocket = websocket_dependency.websocket

    message_handlers = {
        ChatEvent.goes_online: handle_goes_online,
        ChatEvent.goes_offline: handle_goes_offline,
        ChatEvent.typing_start: handle_typing_start,
        ChatEvent.typing_stop: handle_typing_stop,
        ChatEvent.enter_chat: handle_enter_chat,
        ChatEvent.exit_chat: handle_exit_chat,
        ChatEvent.sent_message: handle_sent_message,
        ChatEvent.created_chat: handle_created_chat,
    }

    async with WebSocketContextManager(websocket=websocket, user_id=user_id, connect_handler=chat_connect, disconnect_handler=chat_disconnect,
                                       pubsub_generator=chat_pubsub_generator,
                                       message_handlers=message_handlers) as connection:
        await connection.wait_until_disconnected()


# Connection setup
async def chat_connect(user_id: str, websocket: WebSocket):
    await chat_ws_manager.connect(user_id=user_id, websocket=websocket)
    participant_ids: set[str] = await chat_cache_manager.add_user_to_room(user_id=user_id)
    data = {"type": ChatEvent.goes_online.value, "participant_id": user_id}
    tasks = [pubsub_manager.publish(topic=f"chats:home:{pid}", data=data) for pid in participant_ids]
    await asyncio.gather(*tasks)


async def chat_disconnect(user_id: str, websocket: WebSocket):
    await chat_ws_manager.disconnect(user_id=user_id, websocket=websocket)
    participant_ids: set[str] = await chat_cache_manager.remove_user_from_room(user_id)
    data = {"type": ChatEvent.goes_offline.value, "participant_id": user_id}
    tasks = [pubsub_manager.publish(topic=f"chats:home:{pid}", data=data) for pid in participant_ids]
    await asyncio.gather(*tasks)


async def chat_pubsub_generator(user_id: str) -> PubSub:
    return await pubsub_manager.subscribe(topic=f"chats:home:{user_id}")


# Event handlers
async def handle_goes_online(user_id: str, data: dict[str, str]):
    my_logger.debug(f"User {data.get('participant_id')} came online")
    await chat_ws_manager.send_personal_message(user_id=user_id, data=data)


async def handle_goes_offline(user_id: str, data: dict):
    my_logger.debug(f"User {data.get('participant_id')} went offline")
    await chat_ws_manager.send_personal_message(user_id=user_id, data=data)


async def handle_typing_start(user_id: str, data: dict):
    my_logger.debug(f"User started typing in {data.get('chat_id')}")
    await chat_ws_manager.send_personal_message(user_id=user_id, data=data)


async def handle_typing_stop(user_id: str, data: dict):
    my_logger.debug(f"User stopped typing in {data.get('chat_id')}")
    await chat_ws_manager.send_personal_message(user_id=user_id, data=data)


async def handle_enter_chat(user_id: str, data: dict):
    my_logger.debug(f"User entered to {data.get('chat_id')} room")
    await chat_ws_manager.send_personal_message(user_id=user_id, data=data)


async def handle_exit_chat(user_id: str, data: dict):
    my_logger.debug(f"User exited from {data.get('chat_id')} room")
    await chat_ws_manager.send_personal_message(user_id=user_id, data=data)


async def handle_sent_message(user_id: str, data: dict):
    my_logger.debug(f"User sent message from {data.get('chat_id')} room")
    await chat_ws_manager.send_personal_message(user_id=user_id, data=data)


async def handle_created_chat(user_id: str, data: dict):
    participant_id = data.get("participant_id")
    chat_id = data.get("chat_id")
    my_logger.debug(f"User {participant_id} created a chat room (ID: {chat_id}) with you ({user_id})")
    await chat_ws_manager.send_personal_message(user_id=user_id, data=data)
