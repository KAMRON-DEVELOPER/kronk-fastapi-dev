from typing import Callable, Awaitable, Dict

from utility.my_logger import my_logger


class EventDispatcher:
    def __init__(self):
        self._handlers: Dict[str, Callable[[dict], Awaitable[None]]] = {}

    def on(self, event_type: str):
        def decorator(func: Callable[[dict], Awaitable[None]]):
            self._handlers[event_type] = func
            return func

        return decorator

    async def dispatch(self, event_type: str, payload: dict):
        handler = self._handlers.get(event_type)
        if handler:
            await handler(payload)
        else:
            my_logger.warning(f"No handler for event: {event_type}")


event_dispatcher = EventDispatcher()


@event_dispatcher.on("goes_online")
async def handle_goes_online(payload: dict):
    # logic for online event
    ...


@event_dispatcher.on("message")
async def handle_message(payload: dict):
    ...
