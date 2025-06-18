import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio.client import PubSub
from settings.my_redis import cache_manager, pubsub_manager
from settings.my_websocket import admin_ws_manager, settings_ws_manager
from utility.my_enums import PubSubTopics
from utility.my_logger import my_logger
from utility.my_types import StatisticsSchema

admin_ws_router = APIRouter()


@admin_ws_router.websocket(path="/metrics")
async def admin_statistics_websocket(websocket: WebSocket):
    await admin_ws_manager.connect(websocket=websocket)
    print("🚧 Client connected")

    statistics = await cache_manager.get_statistics()
    await admin_ws_manager.broadcast(data=statistics.model_dump())

    try:
        while True:
            await asyncio.sleep(1)
            data = await websocket.receive_json()
            my_logger.info(f"📨 received_text in settings_metrics data: {data}")
    except WebSocketDisconnect:
        my_logger.info("👋 websocket connection is closing...")
        await admin_ws_manager.disconnect(websocket=websocket)


@admin_ws_router.websocket(path="/statistics")
async def settings_statistics_websocket(websocket: WebSocket):
    await settings_ws_manager.connect(websocket=websocket)
    my_logger.info("🚧 Client connected")

    statistics: StatisticsSchema = await cache_manager.get_statistics()
    my_logger.info(f"🚧 statistics: {statistics}")
    pubsub: PubSub = await pubsub_manager.subscribe(topic=PubSubTopics.SETTINGS_STATS.value)
    await settings_ws_manager.broadcast(data=statistics.model_dump())

    async def listen_pubsub():
        my_logger.debug("📡 Subscribed and listening to 'settings:stats'...")
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message:
                my_logger.debug(f"message: {message}, type: {type(message)}")
                if message["type"] == "message":
                    updated_statistics = await cache_manager.get_statistics()
                    my_logger.debug(f"updated_statistics: {updated_statistics}")
                    await websocket.send_json(updated_statistics.model_dump())

    listener_task = asyncio.create_task(listen_pubsub())

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        listener_task.cancel()
        await pubsub.close()
        await settings_ws_manager.disconnect(websocket=websocket)
