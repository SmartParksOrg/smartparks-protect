"""Progress of the decoder's walks over retained source events (decision D121).

A walk runs in the decoder, event by event, and nothing in the database says how far it is:
the API counts the events and starts the entry, the decoder moves `done` after every page and
removes the entry when the walk ends, and the Needs attention summary adds what is left to its
queued count. One Redis hash with a field per identity, alive for a day, so a walk that never
finished does not wait for ever.
"""

import json
import uuid
from dataclasses import dataclass
from typing import Any, cast

import redis.asyncio as redis_async

KEY = "reprocess:progress"
TTL_SECONDS = 24 * 3600


@dataclass(frozen=True, slots=True)
class Walk:
    identity_id: uuid.UUID
    device_id: uuid.UUID
    total: int
    done: int

    @property
    def waiting(self) -> int:
        return max(self.total - self.done, 0)


async def start_walk(
    redis: redis_async.Redis, identity_id: uuid.UUID, device_id: uuid.UUID, total: int
) -> None:
    await redis.hset(
        KEY, str(identity_id), json.dumps({"device_id": str(device_id), "total": total, "done": 0})
    )
    await redis.expire(KEY, TTL_SECONDS)


async def advance_walk(redis: redis_async.Redis, identity_id: uuid.UUID, done: int) -> None:
    raw = await redis.hget(KEY, str(identity_id))
    if raw is None:
        return  # the entry aged out, or the walk was asked for before this version
    entry = json.loads(cast(str, raw))
    entry["done"] = done
    await redis.hset(KEY, str(identity_id), json.dumps(entry))
    await redis.expire(KEY, TTL_SECONDS)


async def end_walk(redis: redis_async.Redis, identity_id: uuid.UUID) -> None:
    await redis.hdel(KEY, str(identity_id))


async def walks(redis: redis_async.Redis) -> list[Walk]:
    entries = cast(dict[str, str], await redis.hgetall(KEY))
    result: list[Walk] = []
    for identity_id, raw in entries.items():
        entry: dict[str, Any] = json.loads(raw)
        result.append(
            Walk(
                identity_id=uuid.UUID(identity_id),
                device_id=uuid.UUID(entry["device_id"]),
                total=int(entry["total"]),
                done=int(entry["done"]),
            )
        )
    return result


async def waiting(redis: redis_async.Redis) -> int:
    """How many retained events the walks in progress have not reached yet."""
    return sum(walk.waiting for walk in await walks(redis))
