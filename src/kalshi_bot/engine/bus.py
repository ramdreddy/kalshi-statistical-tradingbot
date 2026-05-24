"""Lightweight asyncio event bus for decoupled producers and consumers."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from kalshi_bot.domain.events import Event, EventType

logger = logging.getLogger(__name__)

EventHandler = Callable[[Event], Awaitable[None]]


class EventBus:
    """Fan-in queue with typed subscriber dispatch."""

    def __init__(self, maxsize: int = 256) -> None:
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self._handlers: dict[EventType, list[EventHandler]] = {}
        self._running = False

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def publish(self, event: Event) -> None:
        await self._queue.put(event)

    async def stop(self) -> None:
        await self.publish(Event(type=EventType.SHUTDOWN, payload=None))

    async def run(self) -> None:
        self._running = True
        while self._running:
            event = await self._queue.get()
            if event.type is EventType.SHUTDOWN:
                self._running = False
                break
            for handler in self._handlers.get(event.type, []):
                try:
                    await handler(event)
                except Exception:
                    logger.exception("handler failed for %s", event.type)
