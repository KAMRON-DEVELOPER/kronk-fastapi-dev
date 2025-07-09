import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio.client import PubSub

from settings.my_dependency import websocketDependency
from settings.my_redis import cache_manager, pubsub_manager
from settings.my_websocket import home_timeline_ws_manager
from utility.my_enums import PubSubTopics
from utility.my_logger import my_logger

feed_ws_router = APIRouter()


@feed_ws_router.websocket("/timeline")
async def home_timeline(websocket_dependency: websocketDependency):
    user_id = websocket_dependency.user_id.hex
    websocket = websocket_dependency.websocket

    pubsub = None
    listener_task = None
    receiver_task = None

    try:
        await home_timeline_ws_manager.connect(user_id=user_id, websocket=websocket)
        topic = PubSubTopics.FEEDS.value.format(follower_id=user_id)
        pubsub = await pubsub_manager.subscribe(topic=topic)
        await cache_manager.add_user_to_feeds(user_id)

        listener_task = asyncio.create_task(_pubsub_listener(pubsub, websocket))
        receiver_task = asyncio.create_task(_websocket_receiver(websocket))

        await asyncio.wait(fs=[listener_task, receiver_task], return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        my_logger.info(f"WebSocket disconnected: {user_id}")
    finally:
        if pubsub is not None:
            await _cleanup_connection(user_id, pubsub, listener_task, receiver_task)


async def _pubsub_listener(pubsub: PubSub, websocket: WebSocket):
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                my_logger.warning(f"message: ${message}, type: {type(message)}")
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
    await home_timeline_ws_manager.disconnect(user_id=user_id)
    await cache_manager.remove_user_from_feeds(user_id)
    if pubsub:
        await pubsub.close()
    my_logger.info(f"Cleaned up connection for {user_id}")
