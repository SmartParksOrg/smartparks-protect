# Data curation

Known data quality problems can be corrected without touching the observation itself: a valid
GNSS fix with a wrong timestamp from a firmware clock bug, a sensor value off by a calibration
offset, an outlier that should not be shown. A correction is an overlay on the canonical record
with its reason, author and time, reversible at any time (architecture 28, ADR 0018, decisions
D80 to D83). Raw source events and payloads are never changed.

## The effective value

Every canonical position and measurement keeps its original `time`, coordinates and value. A
correction writes the corrected value into an overlay column (`curated_time`, `curated_geom`,
`curated_value_num`, `valid`); null there means the original applies. Maps, tracks, the Data
Explorer, rules, exports and outbound integrations read the effective value, which is the
overlay when present and the original otherwise. The original stays visible in the curation
history and in exports of the original view.

Curatable fields (architecture 28.3), nothing else:

| Record | Fields |
| --- | --- |
| position | time, coordinates, validity |
| measurement | time, numeric value, validity |

A record marked invalid disappears from every normal view (map, charts, rules, effective
exports, integrations) but stays in the database and in the original export view.

A timestamp correction reruns the project and entity attribution at the corrected time
(architecture 28.9): a record shifted across a device handover moves to the project and entity
of its new time, and back when reverted. The device's and the entities' current state (latest
position) is recomputed after every apply and revert.

## Single corrections

On the device page (positions) and in the Data Explorer's drill-down rows (measurements),
"curate" opens the dialog: the field, the value now (and the original when already curated),
the corrected value, a structured reason (architecture 28.7) and a comment or evidence. Curated
records carry a "curated" or "invalid" marker that opens the history: effective versus original
per field and every correction on the record with its status.

Corrections on one field form a chain: a new correction supersedes the active one; reverting
the newest brings the previous one back; reverting the last restores the original. An older
correction cannot be reverted while a newer one is active.

## Bulk jobs

Curation, "New bulk job": records (positions or measurements), devices and optionally entities
and metrics, a period by effective time, one transformation and a reason. Transformations
(architecture 28.5): shift time by a number of seconds, mark valid or invalid, add to the value,
scale the value. The preview shows the number of affected records (at most 200,000 per job),
ten samples before and after, and the impact counted on the first 5,000 records: attribution
changes, outbound deliveries already sent, enabled rules. Apply runs in the batch worker (the
export service) as one correction per record, 500 per transaction, with progress on the job.
Revert pops every correction of the job the same way.

With "replay the enabled rules" on, the job ends with a report of what every enabled rule with
a matching trigger would have fired over the corrected window (the existing rule replay). The
report informs; it creates no events and no alerts (decision D82).

## Approval

Project settings, "Corrections need approval" (off by default, decision D81). When on, a
correction or a job proposed by one person stays pending until a different person with the
approve permission approves it; the proposer cannot approve their own. Permissions:
`data:curate` for single corrections, `data:curate_bulk` for jobs, `data:approve`,
`data:revert`. Project admins hold all four; viewers see the workspace and the history.

## Downstream impact

When a corrected record was delivered to an integration before, that delivery is flagged
stale with the reason (architecture 28.10). The Curation workspace, tab "Downstream impact",
and the deliveries log show them; "Resend corrected" queues the corrected object as a new
delivery with the record's curation version. Nothing is resent without that review.

## Exports

Positions and measurements export in the effective view (default) or the original view
(`view=original`: original times and values, invalid rows included with their `valid` column).
"Curation metadata columns" adds `is_curated`, `curated_fields`, `curation_reason`,
`original_time`, `effective_time`, `original_value`, `effective_value`, `curated_by`,
`curated_at` and `curation_job_id` (architecture 28.13, decision D83). The raw view is the
source events dataset.

## Audit and traces

Proposing, applying, approving and reverting corrections and jobs are audited with the record,
field, reason and status. A job keeps its selection, transformation, preview, impact and the
users who created, approved and applied it.

## API

`/api/v1/projects/{project_id}/curation/`: `summary`, `corrections` (list, create, get,
`approve`, `revert`), `history?target_type&target_id&target_time`, `jobs` (list, create with
preview, get, `preview`, `apply`, `approve`, `revert`). Deliveries:
`/integrations/deliveries?stale=true` and `POST /integrations/deliveries/{id}/resend`. Positions
and analytics rows carry `original_time`, `curated_fields`, `valid` and `curation_version`;
`include_invalid=true` shows invalid rows.

## GNSS outliers

A fix that would need an impossible speed from the device's last valid fix is an outlier (decisions D221 to D224): farther than `OUTLIER_MIN_JUMP_M` (1 km) from it and faster than `OUTLIER_MAX_SPEED_MPS` (50 m/s, 180 km/h) between the two. The bounds are loose on purpose: no animal moves that fast, a vehicle rarely, and the jump floor keeps GPS scatter over a short interval from ever triggering. The decoder judges every own fix as it arrives against the last valid fix before it in time (a fix written earlier in the same log file counts, so a raw log is judged in order) and stores a flagged fix `valid = false` with the figures under `attributes.outlier` (the distance, the seconds, the speed, the time of the fix it was judged against, the bounds). The next fix is judged against the last valid one, never against the outlier, so a single wild fix leaves no trace beyond itself.

A flagged fix moves no map, fires no rule, reaches no integration and counts in no analysis; the device's current position stays where it was. An informational event `position_outlier` says so, with the figures in its context, so a rule can notify on it. The processing trace of the delivery names the count.

Approving is a person's decision: Curation, Outliers lists the flagged fixes of the project (device, entity, time, jump, speed, accuracy, where) with "Approve: the fix is real", which writes a set-valid correction with the reason `OUTLIER_APPROVED`, audited and reversible, subject to the project's approval rule like any correction. The device page says how many flagged fixes wait for review. "Find outliers in the past" runs the same rule over a period as a bulk job (`flag_outliers`, positions only): the preview counts the fixes it would flag, applying marks them invalid with their figures, and each flagged fix appears under Outliers for review. A job that flags nothing changes nothing.

The API: `GET /projects/{id}/curation/outliers` (`device_id`, `waiting`, `limit`) lists them with a total and the count waiting; `POST /projects/{id}/curation/corrections` with `field: valid`, `corrected_value: true` and `reason_code: OUTLIER_APPROVED` approves one; the transformation kind `flag_outliers` on `POST /projects/{id}/curation/jobs` runs the sweep. `GET /devices/{id}/data-span` carries `outliers_waiting`.

## A device clock ahead of time

When the decoder finds a device time more than an hour ahead of the delivery, it keeps the record invalid (Needs attention, Clocks ahead, lists the devices). Correct it here with a bulk job on the device: target the positions and then the measurements, the period from the earliest wrong time to the latest, transformation time offset with the negative of the clock's lead, reason Device clock error. The preview shows the rows and the impact; applying moves the rows to their real times. Rows the decoder marked invalid become valid with a second job, transformation validity, over the corrected period. The offset may span a hundred years, which a clock started from a wrong epoch needs (a collar's flash log wrote its status records 39 years ahead). A time correction also rebuilds the device's latest values per metric, so the health card shows the repaired status at once.
