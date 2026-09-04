# ADR 0018: immutable source data and layered interpretation

- Status: accepted
- Date: 2026-09-04
- Decisions: D80, D81, D82, D83

## Context

Architecture 28 distinguishes raw source events, decoded records, canonical records, the curated
effective value and what is presented, and requires corrections to be explicit, versioned,
auditable and reversible overlays that never rewrite the source. Firmware and clock defects can
affect thousands of records at once, a corrected timestamp can change which project and entity
a record belongs to, derived state and outbound deliveries can become stale, and scientific
exports must be able to tell the original from the corrected value.

## Decision

**Overlay columns, originals untouched.** `positions` and `measurements` carry nullable
`curated_time`, `curated_geom` or `curated_value_num`, `valid`, `curated_fields` and
`curation_version`. Null means the original applies, so adding the columns touches no existing
row and the time column that partitions the hypertable is never rewritten. One module
(`shared/curation/effective.py`) defines the effective time, point and value and the time-window
predicate (a disjunction that keeps chunk exclusion for uncurated rows and uses a small partial
index for curated ones); every reader uses it.

**Corrections and jobs are rows.** `data_corrections` holds one correction per record and
field with the value before, the value after, reason, author, approval, status and impact;
`curation_jobs` holds a bulk transformation with its selection, preview and impact, and links
its corrections. Corrections on one field form a chain (active, superseded, reverted) that
pops from the top.

**Recomputation is bounded and reviewed.** A time correction reruns the attribution; the
current state of the device and entities is recomputed; sent deliveries of the record are
flagged stale and resent only on request as a new version; a bulk job may run the existing rule
replay as a report. Analytics are computed live, so nothing is cached to invalidate.

**Approval is a project switch.** Off by default; on, corrections and jobs wait for a second
person with the approve permission.

**Exports name the view.** Effective by default, original on request, with optional curation
metadata columns.

## Consequences

- Corrections are cheap to add and to undo, and the history is complete; readers pay a
  coalesce per row and a second index probe per time window.
- The attribution columns on canonical rows change with a time correction; they are derived
  from the assignments, not observations, and the correction records the values before.
- Bulk jobs run in the export service, so a long job never blocks the API; the job row is the
  progress and the record of what was done.
- Rules are not re-evaluated automatically: a replay report tells what would fire, and a person
  decides. Events already raised on wrong data stay, with their history.
