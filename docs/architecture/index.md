# Architecture

Smart Parks Protect is a monorepo of services orchestrated with Docker Compose. Redis Streams is the event bus, PostgreSQL with PostGIS and TimescaleDB stores everything, MinIO holds files.

The layering, from the concept architecture:

```
external platforms  ->  connectivity adapters  ->  source events  ->  device drivers
                    ->  normalized domain (positions, measurements, states, events)
                    ->  monitor | analyze | rules  ->  automation, control, integrations
```

Connectivity adapters understand external platforms and nothing about devices. Device drivers understand device protocols and nothing about networks. The normalized domain understands Smart Parks entities and data and nothing about either.

Pages in this section are written as the related phases land:

- [Data model](data-model.md)
- Processing pipeline (phase 2)
- Scalability and bounded queries (phase 4)
- [AddaxAI Connect reuse audit](addaxai-connect-reuse-audit.md) (phase 0)

The full concept architecture (draft v16) is `Smart_Parks_Protect_Concept_Architecture.md` in the repository root.
