# 0041. An assignment boundary moves after the fact, with its neighbour, under audit

Date: 2026-10-26

Status: accepted; builds on 0010, 0032 and 0038

## Context

A device's project and entity assignments are half-open ranges that never overlap, and every record is attributed to the project and entity that held the device at the record's own time (ADR 0010). A transfer, a move or a release stamps the moment it was made. The moment the device really changed hands is often known only afterwards: the last uplink in the old project, the hour the collar went on the next animal. On 2026-10-26 SP051307 was moved from Smart Parks to Smart Parks - LP0 and from entity Tim to entity SP051307 "from now", at 15:21:13, while the intended boundary was 14:13:52 the day before, one second after its last KPN uplink. Nothing could move that boundary: a start moved earlier collides with the previous row under the exclusion constraint, the end of one row and the start of the next are two edits in two places, and an edit through the database bypasses the attribution job and leaves no trace of who changed what.

## Decision

A boundary is moved as one thing. The edge named and the matching edge of the row that touches it move together, so the timeline stays as contiguous as it was; a boundary nothing touches moves alone and the preview says whether unassigned time opens or closes. The move is refused in words when the instant lies in the future, would leave this row or the neighbour empty, or would cross another row; an entity row must stay inside a project row of its entity's project, judged against the project rows as they will stand. A project boundary and an entity boundary that share an instant are corrected together in one call, since a transfer changes both.

The records between the old and the new instant change hands through the attribution job of ADR 0032, over that window alone; raw messages are never touched. Every changed row gets an audit row with who, when, the reason the person gave, the old and the new instant and the neighbour, and the timeline read shows the last change per row. The rights follow the operations that made the rows: server admin or project admin of every project involved for a project boundary (the move rule of ADR 0038), `devices:write` in the entities' projects for an entity boundary.

AI clients get the same correction as a write action under the AI action policy, confirmation by default, behind a scope of its own (`assignments:write`), with a summary that names every row, the instants and the window, so a person confirms exactly what a person would do on the page.

## Consequences

A wrong boundary is repaired where the data is read, with the preview saying what moves and the audit saying what moved. The rows keep their own `reason` (why the assignment was made); the correction's reason lives on the audit row. The device page's Assignments tab is the one place for a device's assignment history and its edits; the Overview keeps the current project and entity. The existing endpoints that create, extend and end assignments stand, and a move remains the way to change where a device belongs from a moment on; this is the way to say when.
