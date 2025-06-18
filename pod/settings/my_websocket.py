import asyncio
from typing import Optional

from fastapi import WebSocket
from redis.asyncio import Redis
from settings.my_exceptions import ApiException
from settings.my_redis import my_cache_redis
from utility.my_logger import my_logger


class WebSocketManager:
    def __init__(self, redis: Redis):
        self.redis = redis

        self.authorized_connections: dict[str, WebSocket] = {}
        self.unauthorized_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket, user_id: Optional[str] = None):
        try:
            await websocket.accept()

            if user_id:
                self.authorized_connections[user_id] = websocket
                my_logger.debug(f"📡 User {user_id} connected")
            else:
                self.unauthorized_connections.append(websocket)
                my_logger.debug("👻 Anonymous WebSocket connected")
        except Exception as exception:
            raise ValueError(f"🌋 Exception while accepting the websocket connection: {exception}")

    async def disconnect(self, websocket: Optional[WebSocket] = None, user_id: Optional[str] = None):
        try:
            if user_id:
                self.authorized_connections.pop(user_id, None)
                my_logger.debug(f"👾 User {user_id} disconnected")
            elif websocket:
                self.unauthorized_connections.remove(websocket)
                my_logger.debug("👻 Anonymous WebSocket disconnected")

        except Exception as exception:
            raise ValueError(f"🌋 Exception while disconnecting the websocket connection: {exception}")

    async def send_personal_message(self, user_id: str, data: dict):
        ws: Optional[WebSocket] = self.authorized_connections.get(user_id)
        if ws is None:
            raise ApiException(status_code=400, detail="Connection not found.")

        try:
            await ws.send_json(data=data)
        except Exception as exception:
            raise ValueError(f"🌋 Exception while sending personal message: {exception}")

    async def broadcast(self, data: dict, user_ids: Optional[list[str]] = None):
        targets = [self.authorized_connections[uid] for uid in user_ids if uid in self.authorized_connections] if user_ids else self.unauthorized_connections

        async def safe_send(ws: WebSocket):
            try:
                await ws.send_json(data=data)
            except Exception as exception:
                print(f"🌋 Exception while broadcasting with safe_send: {exception}")

        await asyncio.gather(*(safe_send(ws) for ws in targets))


admin_ws_manager = WebSocketManager(redis=my_cache_redis)

settings_ws_manager = WebSocketManager(redis=my_cache_redis)

home_timeline_ws_manager = WebSocketManager(redis=my_cache_redis)

chat_sw_manager = WebSocketManager(redis=my_cache_redis)
