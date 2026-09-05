"""MQTT subscription with reconnect. Adapters give topics and a message callback."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import aiomqtt

from shared.logger import get_logger

log = get_logger("transport.mqtt")

MqttCallback = Callable[[str, bytes], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class MqttSettings:
    host: str
    port: int = 1883
    username: str | None = None
    password: str | None = None
    tls: bool = False
    client_id: str | None = None


async def subscribe_forever(
    settings: MqttSettings,
    topics: list[str],
    callback: MqttCallback,
    *,
    reconnect_seconds: float = 5.0,
    max_reconnect_seconds: float = 60.0,
) -> None:
    """Subscribe and call `callback(topic, payload)` per message. Reconnects on any error,
    doubling the delay up to `max_reconnect_seconds` while the broker stays away."""
    delay = reconnect_seconds
    while True:
        try:
            async with aiomqtt.Client(
                settings.host,
                port=settings.port,
                username=settings.username,
                password=settings.password,
                identifier=settings.client_id,
                tls_params=aiomqtt.TLSParameters() if settings.tls else None,
            ) as client:
                for topic in topics:
                    await client.subscribe(topic)
                log.info("mqtt subscribed", host=settings.host, topics=topics)
                delay = reconnect_seconds
                async for message in client.messages:
                    payload = (
                        message.payload
                        if isinstance(message.payload, bytes)
                        else bytes(str(message.payload), "utf-8")
                    )
                    await callback(str(message.topic), payload)
        except asyncio.CancelledError:
            raise
        except aiomqtt.MqttError as exc:
            log.warning(
                "mqtt connection lost, reconnecting",
                host=settings.host,
                error=str(exc),
                delay=delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_reconnect_seconds)
