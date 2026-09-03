# 0004. Redis Streams as the event bus

Date: 2026-09-03

Status: accepted

## Context

Normalized domain changes must reach the live map, the rules engine, notifications, integrations and aggregation independently. AddaxAI Connect uses Redis lists with `BRPOP`, which has no acknowledgement, no retry and no dead letter; a worker crash mid-message loses the message. The architecture asks for durable, replayable delivery with per-consumer failure handling, and for an interface that allows a broker swap later.

## Decision

Redis Streams with one consumer group per worker. Messages are acknowledged after the database transaction commits. Failed messages retry with backoff and land in a `<topic>.dead` stream after the configured attempts. Pending messages are reclaimed on restart. Every worker stamps a heartbeat key; fifteen minutes without a stamp is stale. All of this sits behind an `EventBus` interface in `shared/bus.py` so a broker swap touches one module.

## Alternatives considered

- Redis lists as in AddaxAI Connect: no acknowledgement, no replay.
- RabbitMQ or NATS: a second broker to run and back up; not needed at the design envelope.
- Kafka: far beyond the operational budget of a self-hosted conservation deployment.

## Consequences

One broker, already needed for caching. Stream trimming must be configured so memory stays bounded. Workers must be idempotent because delivery is at least once.
