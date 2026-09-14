# 0031. Analysis as an isolated, optional subsystem

Date: 2026-09-14

Status: accepted

## Context

Protect holds every fix a collar sent, curated and attributed to an animal, and shows it on a map, in tables and in charts. What the data does not say by itself, how far an animal moved, how much ground it used, how a herd used the management areas, was computed outside, in QGIS or R, from exports. Tim's brief for phase 1 of the analytics (`docs/ANALYTICS_PHASE1_PLAN.md`) asked for two modules, movement ecology and grazing and rewilding, built so that the core keeps working without them, reads core data and writes only its own tables, fails without touching ingestion or the live map, and can be switched off per server and per project. The brief also asked for the least framework that carries two modules, and for a decision gate before any third.

## Decision

Analysis is a package of its own (`shared/shared/analysis/`) that no core module imports, a test holds that boundary, and a worker of its own (`services/analysis`, the same image, decision D196) that consumes one topic and computes one run at a time under its own statement and wall-clock timeouts. A run is a row (`analysis_runs`) with its parameters, its status and progress, its result document and its error; its polygons are rows of `analysis_geometries` (decision D202); nothing else is written. A module is code with a key, a version, a parameters model and a `run`, registered in a dict on import; two exist. A run expires after 30 days unless a person keeps it by name (decision D197); re-run makes a new run linked to the old one. Subjects are entities (decision D201); management areas are the project's zones and geofences chosen per run (decision D198). The switches are `ANALYSIS_MODULES` on the server, `analysis_modules` in a project's settings and the permission key `analysis:run` (decision D199); with the server switch empty the section, the routes and the worker's work disappear. Dependencies stay at PostGIS, shapely and numpy (decision D200): the KDE is a binned Gaussian kernel by FFT with cell-union isopleths, clusters and areas come from PostGIS. The all-projects scope, dashboard tiles, reports, scheduled re-runs and an MCP tool wait for the gate (decision D203).

## Alternatives considered

- Running analyses in the export worker: fewer processes, but an export waiting on a home range, and one failure mode shared by two features; Tim chose the separate worker for the cleaner isolation.
- Saved analysis definitions as their own table: a kept run already is the saved analysis, with its parameters and its result together.
- A management unit feature type or a project GIS layer: the zones and geofences already exist, and a picked set per run keeps the run reproducible when the features change.
- scipy, pandas or geopandas: each brings a stack the image does not carry; numpy and shapely are already there and the two modules need nothing they lack.
- Results in MinIO: a document under 4 MiB and its polygons in PostGIS are easier to read, export and delete with the row.
- A plug-in loader, a pipeline framework, a metric registry: none is needed by two modules; the gate decides whether a third one changes that.

## Consequences

- The core can be deployed, upgraded and run with analysis off; the analysis tables migrate with the rest and stay empty.
- A slow or failing run costs the analysis worker its time and nothing else; the API only counts and reads rows.
- A third module is a decision, not a drop-in: the gate of the plan's section 20 asks for adoption, performance, maintenance, deployment, interface, scientific usefulness, value against external tools, support and architectural impact first.
