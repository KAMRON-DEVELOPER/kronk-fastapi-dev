import asyncio
import json
from asyncio import Task
from typing import Optional, Callable, Awaitable

from fastapi import WebSocket, WebSocketDisconnect
from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from settings.my_exceptions import ApiException
from settings.my_redis import my_cache_redis, pubsub_manager
from utility.my_enums import ChatEvent
from utility.my_logger import my_logger


class WebSocketManager:
    def __init__(self, redis: Redis):
        self.redis = redis

        self.authorized_connections: dict[str, WebSocket] = {}
        self.unauthorized_connections: list[WebSocket] = []
        self.event_handlers: dict[str, Callable[[dict], Awaitable[None]]] = {}

    def on(self, event_type: str):
        def decorator(func: Callable[[dict], Awaitable[None]]):
            self.event_handlers[event_type] = func
            return func

        return decorator

    async def handle_event(self, event_type: str, payload: dict):
        handler = self.event_handlers.get(event_type)
        if handler:
            await handler(payload)
        else:
            my_logger.warning(f"No handler registered for event: {event_type}")

    async def connect(self, websocket: WebSocket, user_id: Optional[str] = None):
        try:
            await websocket.accept()

            if user_id:
                self.authorized_connections[user_id] = websocket
                my_logger.debug(f"User {user_id} connected")
            else:
                self.unauthorized_connections.append(websocket)
                my_logger.debug("Anonymous WebSocket connected")
        except Exception as exception:
            raise ValueError(f"Exception while accepting the websocket connection: {exception}")

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


class WebSocketContextManager:
    def __init__(
            self,
            websocket: WebSocket,
            connect_handler: Callable[[str, WebSocket], Awaitable[None]],
            disconnect_handler: Callable[[str, WebSocket], Awaitable[None]],
            pubsub_generator: Callable[[str], Awaitable[PubSub]],
            message_handlers: dict[ChatEvent, Callable[[dict], Awaitable[None]]],
            user_id: Optional[str] = None,
    ):
        self.websocket = websocket
        self.user_id = user_id
        self.connect_handler = connect_handler
        self.disconnect_handler = disconnect_handler
        self.pubsub_generator = pubsub_generator
        self.message_handlers = message_handlers
        self.pubsub: Optional[PubSub] = None
        self.tasks: list[Task] = []

    async def __aenter__(self):
        """Context manager entry point"""
        await self._connect()
        return self

    # New method to wait for disconnection
    async def wait_until_disconnected(self):
        try:
            # Wait for either task to complete
            done, pending = await asyncio.wait(self.tasks, return_when=asyncio.FIRST_COMPLETED)
            # Cancel remaining tasks
            for task in pending:
                task.cancel()
            # Wait for cancellation to complete
            await asyncio.gather(*pending, return_exceptions=True)
        except asyncio.CancelledError:
            pass

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit point - automatic cleanup"""
        await self._disconnect()

    async def _connect(self):
        """Establish all connections"""
        await self.connect_handler(self.user_id, self.websocket)
        self.pubsub = await self.pubsub_generator(self.user_id)

        self.tasks = [asyncio.create_task(self._pubsub_listener()), asyncio.create_task(self._websocket_receiver())]

    async def _disconnect(self):
        """Cleanup all resources"""
        for task in self.tasks:
            if not task.done():
                task.cancel()

        if self.pubsub:
            await self.pubsub.close()

        await self.disconnect_handler(self.user_id, self.websocket)

    async def _pubsub_listener(self):
        """Process pubsub messages with registered handlers"""
        try:
            async for message in self.pubsub.listen():
                if isinstance(message, dict):
                    if message.get("type") != "message":
                        continue

                    pubsub_data: Optional[str] = message.get("data")
                    if pubsub_data is None:
                        await self.websocket.send_json(data={"detail": "Pub Sub data came empty!"})
                        continue

                    data = json.loads(pubsub_data)
                    my_logger.debug(f"data from self.pubsub.listen(): {data}")

                    event_type: Optional[str] = data.get("type")

                    if event_type is None:
                        await self.websocket.send_json(data={"detail": "You must presented event type!"})

                    handler: Optional[Callable[[dict], Awaitable[None]]] = self.message_handlers.get(ChatEvent(event_type))
                    if handler is not None:
                        await handler(data)
        except asyncio.CancelledError:
            my_logger.debug("PubSub listener cancelled")
        except ValueError:
            await self.websocket.send_json(data={"detail": "You must send valid event type! 🐛"})
        except Exception as e:
            my_logger.error(f"PubSub error: {e}")

    async def _websocket_receiver(self):
        try:
            while True:
                received_json: dict[str, str] = await self.websocket.receive_json()
                my_logger.debug(f"received_json from user {self.user_id}: {received_json}")

                event_type: Optional[str] = received_json.get("type")

                if event_type is None:
                    await self.websocket.send_json(data={"detail": "You must presented event type!"})

                data = {"type": ChatEvent(event_type).value, "participant_id": self.user_id, "message": received_json}
                await pubsub_manager.publish(topic=f"chats:home:{self.user_id}", data=json.dumps(data))
        except WebSocketDisconnect:
            my_logger.info("Client disconnected gracefully")
            raise
        except asyncio.CancelledError:
            my_logger.debug("WebSocket receiver cancelled")
        except ValueError:
            await self.websocket.send_json(data={"detail": "You must send valid event type! 🐛"})
        except Exception as e:
            my_logger.error(f"WebSocket error: {e}")


admin_ws_manager = WebSocketManager(redis=my_cache_redis)

settings_ws_manager = WebSocketManager(redis=my_cache_redis)

home_timeline_ws_manager = WebSocketManager(redis=my_cache_redis)

chat_ws_manager = WebSocketManager(redis=my_cache_redis)


@chat_ws_manager.on("typing_start")
async def typing_start(data: dict):
    chat_id = data["chat_id"]
    user_id = data["user_id"]
    await chat_ws_manager.broadcast(data={"type": "typing_start", "chat_id": chat_id, "user_id": user_id}, user_ids=[])


@chat_ws_manager.on("typing_stop")
async def typing_stop(data: dict):
    chat_id = data["chat_id"]
    user_id = data["user_id"]
    await chat_ws_manager.broadcast(data={"type": "typing_stop", "chat_id": chat_id, "user_id": user_id}, user_ids=[])
