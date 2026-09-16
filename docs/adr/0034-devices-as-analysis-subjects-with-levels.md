# 0034. Devices as analysis subjects, with a level per indicator

Date: 2026-09-16

Status: accepted

## Context

The analysis framework of phase 22 (ADR 0031) takes entities as its subjects: a collar's fixes belong to the animal it tracked, by the assignment history, and the movement and grazing modules ask about animals. The device performance module (phase 28, decisions D213 to D220) asks about the devices themselves: their battery, their reboots, their fixes, the networks that carry them. A device without an animal, a spare in a drawer or one freshly onboarded, must be analysed like any other, and a device that changed animals inside the period is one subject, not two. The module also has to say whether a figure is worrying: a fleet of a hundred collars is read from a table whose first rows need attention, not from a hundred numbers.

## Decision

Devices are a kind of subject of the framework (D214). `SubjectSelection` takes `device_ids`, `device_type_id` or `all_devices` beside the entity fields; a module declares `subject_kind = "device"`; the API resolves a type or "all" to the devices assigned to the project at some point in the period, applies the member's device scope, refuses an id outside it, and stores the resolved ids so the run stays reproducible. A `Subject` carries its `kind` and, for a device, the entity it `tracked` in the period. The trajectory loader reads a device's own fixes when asked; the movement and grazing modules keep entity subjects unchanged.

Every indicator carries a level, ok, warn or critical (D217). The bounds come from the driver's health fields where it declares them (the OpenCollar battery, temperature, accuracy, time to fix and flash bounds of decision D104), so a device is judged by what its maker says is worrying, and from a catalogue of defaults where it does not; the defaults are named in the result document and in the docs, so a reader sees what "warn" meant. Inside a fleet run every device is ranked per indicator. The catalogue is fixed per area (D216): an indicator is computed when the device reports the data and left out when it does not, and there are no per-run switches.

## Alternatives considered

- A device as an entity of a special type: a device is not a thing the project tracks, and the assignment history, the scope and the pages all treat the two apart; pretending otherwise would leak into every reader.
- Levels by the fleet's distribution alone (a device is worrying when it is worse than most): a fleet of failing collars would show green; the fleet's rank stays as the second dimension.
- Per-run indicator switches: they multiply the result shapes the page, the report and the docs must describe; hiding an indicator the device does not report gives the same effect without them.

## Consequences

The framework's subject model has two kinds and the API branches on the module's declaration; the reader's scope applies to devices through `device_visible`. The run row's module check admits the new key (migration 0036) and `ANALYSIS_MODULES` names it by default. The report engine renders a fleet table with level dots and a section per device, so a report over many devices stays readable. The defaults live in one place, `shared/analysis/primitives/levels.py`, and changing one is a documented decision, not a tweak in a module.
