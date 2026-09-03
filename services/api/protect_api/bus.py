"""One bus connection per API process, shared by the endpoints that publish."""

from functools import lru_cache

from shared.bus import RedisStreamsBus


@lru_cache
def get_bus() -> RedisStreamsBus:
    return RedisStreamsBus()
