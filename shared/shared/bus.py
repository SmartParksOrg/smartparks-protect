"""Event bus on Redis Streams (decision D4).

One stream per topic, one consumer group per worker. A handler acknowledges by returning; a
handler that raises leaves the message pending and it is re-delivered after a backoff that
doubles with every attempt. After `bus_max_attempts` deliveries, or at once when the handler
raises an `ApplicationError` that is not retryable, the message goes to `<topic>.dead` with the
error and is acknowledged. Pending messages of a crashed consumer are reclaimed by any consumer
of the group on the same backoff rule. Streams are trimmed to an approximate maximum length
(decision D33). Every worker stamps a heartbeat key each loop; fifteen minutes without a stamp
means stale.

Topics are `<object>.<verb>` in past tense. Messages carry `schema_version` (ADR 0006); a
consumer that sees a version it does not know dead-letters the message.
"""

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, cast

import redis.asyncio as redis_async
from redis.exceptions import ResponseError

from shared.config import get_settings
from shared.enums import ErrorCode
from shared.logger import get_logger, trace_id_var
from shared.timeutil import utc_now
from shared.trace import ApplicationError

log = get_logger("bus")


class Topic:
    SOURCE_EVENT_RECEIVED = "source_event.received"
    POSITION_CREATED = "position.created"
    MEASUREMENT_CREATED = "measurement.created"
    DEVICE_STATE_CHANGED = "device.state_changed"
    EVENT_CREATED = "event.created"
    ALERT_CREATED = "alert.created"
    COMMAND_UPDATED = "command.updated"
    DELIVERY_UPDATED = "delivery.updated"
    NEEDS_ATTENTION_CREATED = "needs_attention.created"
    EXPORT_REQUESTED = "export.requested"
    INTEGRATION_BACKFILL_REQUESTED = "integration.backfill_requested"


SCHEMA_VERSION = 1
HEARTBEAT_PREFIX = "heartbeat:"


@dataclass(frozen=True, slots=True)
class Message:
    topic: str
    payload: dict[str, Any]
    schema_version: int = SCHEMA_VERSION
    trace_id: str | None = None
    published_at: datetime = field(default_factory=utc_now)
    id: str | None = None
    delivery_count: int = 1

    def to_fields(self) -> dict[str, str]:
        return {
            "data": json.dumps(self.payload, default=str),
            "schema_version": str(self.schema_version),
            "trace_id": self.trace_id or "",
            "published_at": self.published_at.isoformat(),
        }

    @classmethod
    def from_fields(
        cls, topic: str, message_id: str, fields: dict[str, str], delivery_count: int = 1
    ) -> "Message":
        return cls(
            topic=topic,
            payload=json.loads(fields["data"]),
            schema_version=int(fields.get("schema_version", "1")),
            trace_id=fields.get("trace_id") or None,
            published_at=datetime.fromisoformat(fields["published_at"]),
            id=message_id,
            delivery_count=delivery_count,
        )


Handler = Callable[[Message], Awaitable[None]]


class EventBus(Protocol):
    async def publish(
        self, topic: str, payload: dict[str, Any], *, trace_id: str | None = None
    ) -> str: ...

    async def consume(
        self, topic: str, group: str, consumer: str, handler: Handler, *, once: bool = False
    ) -> int: ...

    async def heartbeat(self, worker: str) -> None: ...

    async def close(self) -> None: ...


def dead_topic(topic: str) -> str:
    return f"{topic}.dead"


class RedisStreamsBus:
    def __init__(self, url: str | None = None) -> None:
        settings = get_settings()
        self.settings = settings
        self.redis = redis_async.from_url(
            url or settings.redis_url,
            decode_responses=True,
            socket_timeout=30,
            socket_connect_timeout=5,
        )
        self._stop = asyncio.Event()

    async def close(self) -> None:
        await self.redis.aclose()

    def stop(self) -> None:
        self._stop.set()

    # Publishing

    async def publish(
        self, topic: str, payload: dict[str, Any], *, trace_id: str | None = None
    ) -> str:
        message = Message(topic=topic, payload=payload, trace_id=trace_id or trace_id_var.get())
        message_id = await self.redis.xadd(
            topic,
            cast("dict[Any, Any]", message.to_fields()),
            maxlen=self.settings.bus_maxlen,
            approximate=True,
        )
        return cast(str, message_id)

    async def publish_dead(self, topic: str, message: Message, error: str, code: str) -> str:
        fields = message.to_fields()
        fields.update(
            {
                "original_id": message.id or "",
                "error": error[:2000],
                "error_code": code,
                "delivery_count": str(message.delivery_count),
                "dead_at": utc_now().isoformat(),
            }
        )
        dead_id = await self.redis.xadd(
            dead_topic(topic),
            cast("dict[Any, Any]", fields),
            maxlen=self.settings.bus_dead_maxlen,
            approximate=True,
        )
        return cast(str, dead_id)

    # Consuming

    async def ensure_group(self, topic: str, group: str) -> None:
        try:
            await self.redis.xgroup_create(topic, group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def backoff_seconds(self, delivery_count: int) -> float:
        return float(self.settings.bus_retry_base_seconds * (2 ** max(delivery_count - 1, 0)))

    async def consume(
        self,
        topic: str,
        group: str,
        consumer: str,
        handler: Handler,
        *,
        once: bool = False,
        concurrency: int | None = None,
    ) -> int:
        """Consume until stopped. With `once`, handle what is available now and return the count
        of handled messages (used by tests and one-shot commands).

        A batch is handled in lanes: messages with the same `device_id` in their payload stay in
        order in one lane, different lanes run concurrently (`BUS_CONCURRENCY` lanes at most).
        Handlers are idempotent by design (canonical keys, time-guarded current state), so the
        ordering across devices does not matter, but keeping one device sequential avoids
        needless unique-key collisions."""
        await self.ensure_group(topic, group)
        lanes = concurrency or self.settings.bus_concurrency
        handled = 0
        while not self._stop.is_set():
            await self.heartbeat(consumer)
            handled += await self._reclaim(topic, group, consumer, handler)
            response = cast(
                "list[tuple[str, list[tuple[str, dict[str, str]]]]]",
                await self.redis.xreadgroup(
                    group, consumer, {topic: ">"}, count=lanes * 4, block=None if once else 2000
                ),
            )
            batch = response[0][1] if response else []
            messages = [
                Message.from_fields(topic, message_id, fields) for message_id, fields in batch
            ]
            await self._handle_batch(topic, group, messages, handler, lanes)
            handled += len(messages)
            if once:
                return handled
        return handled

    async def _handle_batch(
        self, topic: str, group: str, messages: list[Message], handler: Handler, lanes: int
    ) -> None:
        if len(messages) <= 1 or lanes <= 1:
            for message in messages:
                await self._handle(topic, group, message, handler)
            return
        by_lane: dict[str, list[Message]] = {}
        for message in messages:
            key = str(message.payload.get("device_id") or message.id)
            by_lane.setdefault(key, []).append(message)
        semaphore = asyncio.Semaphore(lanes)

        async def run(lane: list[Message]) -> None:
            async with semaphore:
                for message in lane:
                    await self._handle(topic, group, message, handler)

        await asyncio.gather(*(run(lane) for lane in by_lane.values()))

    async def _reclaim(self, topic: str, group: str, consumer: str, handler: Handler) -> int:
        """Re-deliver pending messages whose backoff has passed; dead-letter exhausted ones."""
        pending = cast(
            "list[dict[str, Any]]",
            await self.redis.xpending_range(topic, group, min="-", max="+", count=100),
        )
        handled = 0
        for entry in pending:
            delivery_count = int(entry["times_delivered"])
            idle_seconds = int(entry["time_since_delivered"]) / 1000
            if idle_seconds < self.backoff_seconds(delivery_count):
                continue
            claimed = cast(
                "list[tuple[str, dict[str, str]]]",
                await self.redis.xclaim(
                    topic,
                    group,
                    consumer,
                    min_idle_time=int(idle_seconds * 1000),
                    message_ids=[entry["message_id"]],
                ),
            )
            for message_id, fields in claimed:
                message = Message.from_fields(
                    topic, message_id, fields, delivery_count=delivery_count + 1
                )
                await self._handle(topic, group, message, handler)
                handled += 1
        return handled

    async def _handle(self, topic: str, group: str, message: Message, handler: Handler) -> None:
        assert message.id is not None
        token = trace_id_var.set(message.trace_id)
        try:
            if message.schema_version > SCHEMA_VERSION:
                await self._dead_letter(
                    topic,
                    group,
                    message,
                    ErrorCode.SCHEMA_VERSION_UNSUPPORTED,
                    f"schema_version {message.schema_version} is newer than {SCHEMA_VERSION}",
                )
                return
            try:
                await handler(message)
            except ApplicationError as error:
                if error.retryable and message.delivery_count < self.settings.bus_max_attempts:
                    log.warning(
                        "handler failed, will retry",
                        topic=topic,
                        message_id=message.id,
                        attempt=message.delivery_count,
                        error=str(error),
                    )
                    return
                await self._dead_letter(topic, group, message, error.code, str(error))
                return
            except Exception as exc:
                if message.delivery_count < self.settings.bus_max_attempts:
                    log.error(
                        "handler crashed, will retry",
                        topic=topic,
                        message_id=message.id,
                        attempt=message.delivery_count,
                        exc_info=True,
                    )
                    return
                await self._dead_letter(
                    topic, group, message, ErrorCode.INTERNAL_ERROR, f"{type(exc).__name__}: {exc}"
                )
                return
            await self.redis.xack(topic, group, message.id)
        finally:
            trace_id_var.reset(token)

    async def _dead_letter(
        self, topic: str, group: str, message: Message, code: str, error: str
    ) -> None:
        log.error(
            "message dead-lettered",
            topic=topic,
            message_id=message.id,
            error_code=code,
            error=error,
            attempts=message.delivery_count,
        )
        await self.publish_dead(topic, message, error, code)
        assert message.id is not None
        await self.redis.xack(topic, group, message.id)

    # Dead-letter administration

    async def list_dead(self, topic: str, count: int = 100) -> list[dict[str, Any]]:
        entries = cast(
            "list[tuple[str, dict[str, str]]]",
            await self.redis.xrevrange(dead_topic(topic), count=count),
        )
        result = []
        for dead_id, fields in entries:
            result.append(
                {"id": dead_id, "topic": topic, **fields, "payload": json.loads(fields["data"])}
            )
        return result

    async def retry_dead(self, topic: str, dead_id: str) -> str | None:
        entries = cast(
            "list[tuple[str, dict[str, str]]]",
            await self.redis.xrange(dead_topic(topic), min=dead_id, max=dead_id),
        )
        if not entries:
            return None
        _, fields = entries[0]
        message = Message.from_fields(topic, dead_id, fields)
        new_id = await self.publish(topic, message.payload, trace_id=message.trace_id)
        await self.redis.xdel(dead_topic(topic), dead_id)
        return new_id

    async def resolve_dead(self, topic: str, dead_id: str) -> bool:
        deleted: int = await self.redis.xdel(dead_topic(topic), dead_id)
        return deleted > 0

    async def dead_count(self, topic: str) -> int:
        count: int = await self.redis.xlen(dead_topic(topic))
        return count

    # Liveness

    async def heartbeat(self, worker: str) -> None:
        await self.redis.set(HEARTBEAT_PREFIX + worker, utc_now().isoformat())

    async def heartbeats(self) -> dict[str, datetime | None]:
        keys = [key async for key in self.redis.scan_iter(match=HEARTBEAT_PREFIX + "*")]
        result: dict[str, datetime | None] = {}
        for key in keys:
            value = cast("str | None", await self.redis.get(key))
            result[str(key).removeprefix(HEARTBEAT_PREFIX)] = (
                datetime.fromisoformat(value) if value else None
            )
        return result

    async def lag(self, topic: str, group: str) -> int:
        """Entries not yet delivered to the group, or the stream length when the group is new."""
        try:
            groups = await self.redis.xinfo_groups(topic)
        except ResponseError:
            return 0
        for info in groups:
            if info["name"] == group:
                lag = info.get("lag")
                return int(lag) if lag is not None else 0
        length: int = await self.redis.xlen(topic)
        return length


def is_stale(stamp: datetime | None, now: datetime | None = None) -> bool:
    if stamp is None:
        return True
    minutes = get_settings().heartbeat_stale_minutes
    return ((now or utc_now()) - stamp).total_seconds() > minutes * 60


def new_trace_id() -> str:
    return str(uuid.uuid4())
