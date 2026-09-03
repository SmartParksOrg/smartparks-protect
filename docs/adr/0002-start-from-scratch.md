# 0002. Start from scratch, reuse AddaxAI Connect patterns

Date: 2026-09-03

Status: accepted

## Context

AddaxAI Connect is a working self-hosted camera trap platform by the same developer, with authentication, projects with role-based access, Redis-based workers, PostgreSQL, MinIO, Ansible deployment, notifications and a React frontend. The concept architecture proposes deriving Smart Parks Protect from it. The [reuse audit](../architecture/addaxai-connect-reuse-audit.md) found that the generic parts are tightly coupled to the camera and AI domain (one 50 KB models file, image-specific queue payloads, no database tests, Leaflet and Chart.js where this project needs MapLibre and ECharts).

## Decision

Smart Parks Protect is written from scratch. AddaxAI Connect is the reference for patterns: the invitation flow, RBAC dependencies, worker liveness heartbeats, structured logging, Ansible roles, backup interlocks, the frontend conventions document and the screenshot sweep. Single files may be copied when a pattern is worth taking as is. Nothing is copied blindly. The reuse audit records per mechanism whether it is mirrored, adapted or left out.

## Alternatives considered

- Fork the repository and remove the camera domain: leaves coupling and dead code, and every later AddaxAI Connect change conflicts.
- Import AddaxAI Connect modules as a dependency: the modules are not designed as a library and would pin this project to its release cycle.

## Consequences

More code to write in phases 0 and 1. A clean domain without camera concepts. Both projects can evolve independently, and improvements found here (streams with acknowledgement, database tests, a lockfile) can be ported back.
