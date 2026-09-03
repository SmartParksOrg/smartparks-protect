# 0005. Backend and frontend stack

Date: 2026-09-03

Status: accepted

## Context

The stack should let AddaxAI Connect patterns transfer, use current versions, and support the map, chart and form requirements of the architecture (5,000 entities on a WebGL map, large time-series charts, a rules form builder).

## Decision

Backend: Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, Pydantic 2, FastAPI-Users, one `uv` workspace with one lockfile and exact pins, `ruff` and `mypy` strict. Frontend: React 19, Vite, TypeScript strict, Tailwind 4, shadcn/ui, TanStack Query, Zustand, React Hook Form with Zod, React Router 7, MapLibre GL JS, Apache ECharts, Vitest and Playwright. Brand colours #52735E and #90AE9B as CSS variables.

## Alternatives considered

- Leaflet as in AddaxAI Connect: DOM markers do not reach the 5,000 entity target; MapLibre renders vector tiles from PostGIS.
- Chart.js as in AddaxAI Connect: no large-data mode or dataZoom; ECharts has both and state timelines.
- Pip with requirements files as in AddaxAI Connect: no lockfile, per-service resolution conflicts. The uv workspace resolves everything once.

## Consequences

Six of the frontend libraries have no precedent in AddaxAI Connect and are set up from first principles. The uv workspace excludes `services/frontend`, which is a Node project.
