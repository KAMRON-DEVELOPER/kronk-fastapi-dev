import asyncio
import json
import time
from asyncio import Task
from typing import Optional, Callable, Awaitable

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
from redis.asyncio import Redis
from redis.asyncio.client import PubSub

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
            my_logger.exception("Exception while accepting the websocket connection: {exception}")
            raise ValueError(f"Exception while accepting the websocket connection: {exception}")

    async def disconnect(self, websocket: Optional[WebSocket] = None, user_id: Optional[str] = None):
        try:
            if user_id:
                self.authorized_connections.pop(user_id, None)
                my_logger.debug(f"User with {user_id} ID disconnected")
            elif websocket:
                self.unauthorized_connections.remove(websocket)
                my_logger.debug("Anonymous WebSocket disconnected")

        except Exception as exception:
            my_logger.exception(f"Exception while disconnecting the websocket connection: {exception}")
            raise ValueError(f"Exception while disconnecting the websocket connection: {exception}")

    async def send_personal_message(self, user_id: str, data: dict):
        ws: Optional[WebSocket] = self.authorized_connections.get(user_id)
        if ws is None:
            my_logger.exception(f"Websocket connection not exists with {user_id}")

        try:
            await ws.send_json(data=data)
        except Exception as exception:
            my_logger.exception(f"Exception while sending personal message: {exception}")
            raise ValueError(f"Exception while sending personal message: {exception}")

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
            message_handlers: dict[ChatEvent, Callable[[str, dict], Awaitable[None]]],
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
        await self._connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._disconnect()

    async def _connect(self):
        await self.connect_handler(self.user_id, self.websocket)
        self.pubsub = await self.pubsub_generator(self.user_id)
        self.tasks = [
            asyncio.create_task(self._pubsub_listener()),
            asyncio.create_task(self._websocket_receiver())
        ]

    async def _disconnect(self):
        if self.pubsub:
            try:
                await self.pubsub.close()
            except Exception as e:
                my_logger.exception(f"Failed to close pubsub: {e}")

        try:
            await self.disconnect_handler(self.user_id, self.websocket)
        except Exception as e:
            my_logger.exception(f"Disconnect handler error: {e}")

        if self.websocket.client_state == WebSocketState.CONNECTED:
            try:
                await self.websocket.close()
            except Exception as e:
                my_logger.exception(f"Exception while closing WebSocket: {e}")

    async def wait_until_disconnected(self):
        try:
            done, pending = await asyncio.wait(self.tasks, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            # Handle external cancellation
            for task in self.tasks:
                if not task.done() and not task.cancelled():
                    task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
        else:
            # Cancel pending tasks
            for task in pending:
                if not task.done() and not task.cancelled():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    async def _pubsub_listener(self):
        """Listen to Redis pub/sub messages and dispatch them to registered handlers."""
        try:
            async for message in self.pubsub.listen():
                if message.get("type") != "message":
                    continue

                pubsub_data = message.get("data")
                if pubsub_data is None:
                    continue

                try:
                    if isinstance(pubsub_data, bytes):
                        pubsub_data = pubsub_data.decode("utf-8")
                    data: dict = json.loads(pubsub_data)
                except (TypeError, json.JSONDecodeError, UnicodeDecodeError) as e:
                    my_logger.error(f"Failed to decode pubsub message: {e}")
                    continue

                event_type: Optional[str] = data.get("type")
                if event_type is None:
                    my_logger.warning(f"Missing 'type' field in event data: {data}")
                    await self.websocket.send_json({"detail": "Missing event type in pubsub message."})
                    continue

                try:
                    chat_event = ChatEvent(event_type)
                except ValueError:
                    my_logger.exception(f"Invalid event type received: '{event_type}'")
                    await self.websocket.send_json({"detail": f"Invalid event type: '{event_type}'."})
                    continue

                handler: Optional[Callable[[str, dict], Awaitable[None]]] = self.message_handlers.get(chat_event)
                if handler is None:
                    my_logger.warning(f"No handler registered for event type: '{event_type}'")
                    await self.websocket.send_json({"detail": f"No handler for event type: '{event_type}'."})
                    continue

                try:
                    await handler(self.user_id, data)
                except Exception as e:
                    my_logger.exception(f"Error while handling event '{event_type}': {e}")
                    await self.websocket.send_json({"detail": f"An error occurred while handling event: '{event_type}'."})
        except asyncio.CancelledError:
            my_logger.debug("PubSub listener cancelled")
        except Exception as e:
            my_logger.exception(f"Unexpected error in pubsub listener: {e}")

    async def _websocket_receiver(self):
        """Receive incoming WebSocket messages and handle heartbeat checks."""
        last_activity = time.time()
        received_json: Optional[dict] = None

        try:
            while self.websocket.client_state == WebSocketState.CONNECTED:
                try:
                    received_json = await asyncio.wait_for(self.websocket.receive_json(), timeout=30.0)
                    last_activity = time.time()
                except asyncio.TimeoutError:
                    if time.time() - last_activity > 60:
                        my_logger.warning("Connection timeout, disconnecting")
                        break
                    try:
                        await self.websocket.send_json({"type": "heartbeat"})
                    except WebSocketDisconnect:
                        my_logger.info("Client disconnected on heartbeat")
                        break
                    except Exception as e:
                        my_logger.warning(f"Heartbeat send failed: {e}")
                        break
                    continue
                except WebSocketDisconnect:
                    my_logger.info("Client disconnected")
                    break
                except Exception as e:
                    my_logger.warning(f"Invalid message: {e}")
                    continue

                event_type: Optional[str] = received_json.get("type")
                if event_type is None:
                    await self.websocket.send_json({"detail": "Missing event type."})
                    continue

                if event_type == "heartbeat":
                    await self.websocket.send_json({"type": "heartbeat_ack"})
                    continue

                try:
                    ChatEvent(event_type)
                except ValueError:
                    my_logger.exception(f"Invalid event type received: '{event_type}'")
                    await self.websocket.send_json({"detail": f"Invalid event type: '{event_type}'."})
                    continue

                if "participant_id" not in received_json:
                    my_logger.exception("Participant ID is required.")
                    await self.websocket.send_json({"detail": "Participant ID is required."})
                    continue

                await pubsub_manager.publish(topic=f"chats:home:{self.user_id}", data=received_json)
        except asyncio.CancelledError:
            my_logger.debug("WebSocket receiver cancelled")
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
