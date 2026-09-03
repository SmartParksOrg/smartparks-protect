"""Event bus against the real Redis from the compose stack."""

import asyncio
import uuid

import pytest
import pytest_asyncio

from shared.bus import Message, RedisStreamsBus, dead_topic, is_stale
from shared.config import get_settings
from shared.enums import ErrorCode
from shared.timeutil import utc_now
from shared.trace import ApplicationError

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def bus():
    bus = RedisStreamsBus()
    topics: list[str] = []
    original = bus.publish

    async def tracking_publish(topic, payload, *, trace_id=None):
        if topic not in topics:
            topics.append(topic)
        return await original(topic, payload, trace_id=trace_id)

    bus.publish = tracking_publish  # type: ignore[method-assign]
    yield bus
    for topic in topics:
        await bus.redis.delete(topic, dead_topic(topic))
    await bus.close()


def topic_name() -> str:
    return f"test.{uuid.uuid4().hex[:8]}"


async def test_publish_consume_ack(bus):
    topic = topic_name()
    seen: list[Message] = []

    async def handler(message: Message) -> None:
        seen.append(message)

    await bus.publish(topic, {"n": 1}, trace_id="t-1")
    await bus.publish(topic, {"n": 2})
    handled = await bus.consume(topic, "g", "c1", handler, once=True)
    assert handled == 2
    assert [m.payload["n"] for m in seen] == [1, 2]
    assert seen[0].trace_id == "t-1"
    pending = await bus.redis.xpending(topic, "g")
    assert pending["pending"] == 0


async def test_retryable_failure_is_redelivered_then_dead_lettered(bus, monkeypatch):
    topic = topic_name()
    settings = get_settings()
    monkeypatch.setattr(settings, "bus_retry_base_seconds", 0.0)
    monkeypatch.setattr(settings, "bus_max_attempts", 3)
    attempts: list[int] = []

    async def handler(message: Message) -> None:
        attempts.append(message.delivery_count)
        raise ApplicationError(
            code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
            message="down",
            component="test",
            retryable=True,
        )

    await bus.publish(topic, {"x": 1})
    await bus.consume(topic, "g", "c1", handler, once=True)  # attempt 1, stays pending
    await bus.consume(topic, "g", "c1", handler, once=True)  # attempt 2 via reclaim
    await bus.consume(topic, "g", "c1", handler, once=True)  # attempt 3: dead letter
    assert attempts == [1, 2, 3]
    dead = await bus.list_dead(topic)
    assert len(dead) == 1
    assert dead[0]["error_code"] == ErrorCode.CONNECTIVITY_UNAVAILABLE
    assert dead[0]["payload"] == {"x": 1}
    assert (await bus.redis.xpending(topic, "g"))["pending"] == 0


async def test_non_retryable_failure_dead_letters_at_once(bus):
    topic = topic_name()

    async def handler(message: Message) -> None:
        raise ApplicationError(
            code=ErrorCode.PAYLOAD_DECODE_FAILED, message="bad port", component="decoder"
        )

    await bus.publish(topic, {"x": 1})
    await bus.consume(topic, "g", "c1", handler, once=True)
    dead = await bus.list_dead(topic)
    assert len(dead) == 1 and dead[0]["error_code"] == ErrorCode.PAYLOAD_DECODE_FAILED
    assert (await bus.redis.xpending(topic, "g"))["pending"] == 0


async def test_retry_dead_republishes(bus):
    topic = topic_name()
    calls = 0

    async def failing(message: Message) -> None:
        raise ApplicationError(
            code=ErrorCode.PAYLOAD_DECODE_FAILED, message="bad", component="decoder"
        )

    async def working(message: Message) -> None:
        nonlocal calls
        calls += 1

    await bus.publish(topic, {"x": 2})
    await bus.consume(topic, "g", "c1", failing, once=True)
    dead = await bus.list_dead(topic)
    new_id = await bus.retry_dead(topic, dead[0]["id"])
    assert new_id is not None
    assert await bus.dead_count(topic) == 0
    await bus.consume(topic, "g", "c1", working, once=True)
    assert calls == 1


async def test_unknown_schema_version_is_dead_lettered(bus):
    topic = topic_name()

    async def handler(message: Message) -> None:
        raise AssertionError("must not be called")

    fields = Message(topic=topic, payload={"v": 9}, schema_version=99).to_fields()
    await bus.redis.xadd(topic, fields)
    await bus.consume(topic, "g", "c1", handler, once=True)
    dead = await bus.list_dead(topic)
    assert dead and dead[0]["error_code"] == ErrorCode.SCHEMA_VERSION_UNSUPPORTED
    await bus.redis.delete(topic, dead_topic(topic))


async def test_pending_of_crashed_consumer_is_reclaimed(bus, monkeypatch):
    topic = topic_name()
    monkeypatch.setattr(get_settings(), "bus_retry_base_seconds", 0.0)
    await bus.publish(topic, {"x": 3})
    await bus.ensure_group(topic, "g")
    # consumer c1 reads and dies before acking
    await bus.redis.xreadgroup("g", "c1", {topic: ">"}, count=1)
    seen: list[int] = []

    async def handler(message: Message) -> None:
        seen.append(message.delivery_count)

    await asyncio.sleep(0.01)
    await bus.consume(topic, "g", "c2", handler, once=True)
    assert seen == [2]


async def test_heartbeat_and_staleness(bus):
    name = f"test-worker-{uuid.uuid4().hex[:6]}"
    await bus.heartbeat(name)
    stamps = await bus.heartbeats()
    assert not is_stale(stamps[name])
    assert is_stale(None)
    assert is_stale(utc_now(), now=utc_now().replace(year=utc_now().year + 1))
    await bus.redis.delete(f"heartbeat:{name}")


async def test_lag_counts_undelivered(bus):
    topic = topic_name()
    await bus.publish(topic, {"a": 1})
    await bus.publish(topic, {"a": 2})
    await bus.ensure_group(topic, "g")
    assert await bus.lag(topic, "g") == 2
