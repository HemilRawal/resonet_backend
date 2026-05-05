"""
Redis Pub/Sub message broker with transparent asyncio.Queue fallback.
All inter-agent communication flows through this module.
If Redis is unavailable, switches to in-process queues automatically — demo never crashes.
"""

import asyncio
import dataclasses
import json
import logging
from typing import Any, Callable, Dict, List, Optional

import config

logger = logging.getLogger(__name__)


def _serialize(message: Any) -> str:
    """Convert a dataclass (or dict) to a JSON string."""
    if dataclasses.is_dataclass(message) and not isinstance(message, type):
        return json.dumps(dataclasses.asdict(message))
    if isinstance(message, dict):
        return json.dumps(message)
    return json.dumps(str(message))


class MessageBroker:
    """
    Unified publish/subscribe interface.
    Tries Redis on connect(); falls back to per-channel asyncio.Queues if unavailable.
    """

    def __init__(self) -> None:
        self.use_fallback: bool = False
        self._redis: Optional[Any] = None
        self._pubsub: Optional[Any] = None
        self._queues: Dict[str, asyncio.Queue] = {}
        self._subscribers: Dict[str, List[Callable]] = {}
        self._listener_tasks: List[asyncio.Task] = []

    async def connect(self) -> None:
        """Attempt Redis connection; activate in-process fallback on failure."""
        try:
            import redis.asyncio as aioredis
            client = aioredis.from_url(config.REDIS_URL, decode_responses=True)
            await client.ping()
            self._redis = client
            self._pubsub = client.pubsub()
            self.use_fallback = False
            logger.info("MessageBroker connected to Redis at %s", config.REDIS_URL)
        except Exception as exc:
            logger.warning(
                "Redis unavailable — using in-process fallback (%s)", exc
            )
            self.use_fallback = True

    def _get_queue(self, channel: str) -> asyncio.Queue:
        if channel not in self._queues:
            self._queues[channel] = asyncio.Queue()
        return self._queues[channel]

    async def publish(self, channel: str, message: Any) -> None:
        """Publish a dataclass message to a channel."""
        payload = _serialize(message)
        if self.use_fallback:
            queue = self._get_queue(channel)
            await queue.put(payload)
            # Dispatch inline to any registered callbacks for this channel
            for cb in self._subscribers.get(channel, []):
                try:
                    await cb(json.loads(payload))
                except Exception as exc:
                    logger.error("Fallback callback error on channel %s: %s", channel, exc)
        else:
            try:
                await self._redis.publish(channel, payload)
            except Exception as exc:
                logger.error("Redis publish failed on %s: %s", channel, exc)

    async def subscribe(self, channel: str, callback: Callable) -> None:
        """Register a callback for messages on a channel."""
        if channel not in self._subscribers:
            self._subscribers[channel] = []
        self._subscribers[channel].append(callback)

        if not self.use_fallback and self._pubsub is not None:
            await self._pubsub.subscribe(**{channel: self._make_redis_handler(callback)})
            task = asyncio.create_task(self._redis_listener())
            self._listener_tasks.append(task)

    def _make_redis_handler(self, callback: Callable) -> Callable:
        async def handler(message: dict) -> None:
            if message.get("type") == "message":
                try:
                    data = json.loads(message["data"])
                    await callback(data)
                except Exception as exc:
                    logger.error("Redis callback error: %s", exc)
        return handler

    async def _redis_listener(self) -> None:
        """Background loop that processes incoming Redis pub/sub messages."""
        async for message in self._pubsub.listen():
            if message["type"] == "message":
                channel = message["channel"]
                try:
                    data = json.loads(message["data"])
                    for cb in self._subscribers.get(channel, []):
                        await cb(data)
                except Exception as exc:
                    logger.error("Redis listener error: %s", exc)

    async def broadcast(self, message: Any) -> None:
        """Publish to the global broadcast channel."""
        await self.publish(config.CHANNEL_BROADCAST, message)

    async def close(self) -> None:
        """Clean up all connections and tasks."""
        for task in self._listener_tasks:
            task.cancel()
        if self._pubsub:
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()
