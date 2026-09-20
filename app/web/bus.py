"""Внутрипроцессная шина событий для WebSocket.

Инстанс один и останется одним (numReplicas: 1), оператор тоже один, поэтому
внешний брокер здесь — лишний сервис и лишняя точка отказа.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

MAX_QUEUE = 100


class Bus:
    def __init__(self, max_queue: int = MAX_QUEUE) -> None:
        self._queues: set[asyncio.Queue] = set()
        self._max_queue = max_queue

    @property
    def subscribers(self) -> int:
        return len(self._queues)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        self._queues.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._queues.discard(queue)

    async def publish(self, event: dict) -> int:
        delivered = 0
        for queue in list(self._queues):
            try:
                queue.put_nowait(event)
                delivered += 1
            except asyncio.QueueFull:
                # Отставший клиент не должен тормозить остальных и копить память.
                logger.warning("очередь подписчика переполнена, событие отброшено")
        return delivered
