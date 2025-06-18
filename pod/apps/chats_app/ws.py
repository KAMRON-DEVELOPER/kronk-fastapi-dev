import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio.client import PubSub
from settings.my_dependency import websocketDependency
from settings.my_redis import cache_manager, pubsub_manager
from settings.my_websocket import chat_sw_manager
from utility.my_logger import my_logger

chat_ws_router = APIRouter()


@chat_ws_router.websocket("/home")
async def enter_home(websocket_dependency: websocketDependency):
    user_id = websocket_dependency.user_id.hex
    websocket = websocket_dependency.websocket

    pubsub = None
    listener_task = None
    receiver_task = None

    try:
        await chat_sw_manager.connect(user_id=user_id, websocket=websocket)
        pubsub = await pubsub_manager.subscribe(f"chat:{user_id}:home")
        await cache_manager.add_online_users_in_home_timeline(user_id)

        listener_task = asyncio.create_task(_pubsub_listener(pubsub, websocket))
        receiver_task = asyncio.create_task(_websocket_receiver(websocket))

        await asyncio.wait(fs=[listener_task, receiver_task], return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        my_logger.info(f"WebSocket disconnected: {user_id}")
    finally:
        if pubsub:
            await _cleanup_connection(user_id, pubsub, listener_task, receiver_task)


@chat_ws_router.websocket("/room")
async def enter_room(websocket_dependency: websocketDependency):
    try:
        user_id = websocket_dependency.user_id.hex
        await chat_sw_manager.connect(user_id=user_id, websocket=websocket_dependency.websocket)
        pubsub = await pubsub_manager.subscribe(f"chat:{user_id}:home")
    except Exception as e:
        pass


async def _pubsub_listener(pubsub: PubSub, websocket: WebSocket):
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode()
                await websocket.send_text(data)
    except asyncio.CancelledError:
        my_logger.debug("PubSub listener task cancelled")


async def _websocket_receiver(websocket: WebSocket):
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        my_logger.debug("WebSocket receiver disconnected")


async def _cleanup_connection(user_id: str, pubsub: PubSub, *tasks):
    for task in tasks:
        if task and not task.done():
            task.cancel()
    await chat_sw_manager.disconnect(user_id=user_id)
    await cache_manager.remove_online_users_in_home_timeline(user_id)
    if pubsub:
        await pubsub.close()
    my_logger.info(f"Cleaned up connection for {user_id}")
