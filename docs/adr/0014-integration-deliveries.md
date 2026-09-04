# ADR 0014: integration deliveries are keyed on the object and retried from a table

- Status: accepted
- Date: 2026-09-04
- Decisions: D60, D61, D62

## Context

Architecture 18 asks for durable outbound integrations that never block ingestion: an
EarthRanger outage of hours must not fill the event bus or lose data, an object must not reach a
target twice, and an administrator must see what was sent, when, with which response. The
open decision from architecture section 32 was how deliveries are made idempotent.

## Decision

Every forwarded object gets one row in `integration_deliveries` keyed on (integration, object
type, object id, object version) with a unique index. Positions and measurements are version 1;
events carry a version that curation can raise later, so a corrected event becomes a new
delivery while the old one stays in the log. Backfill inserts rows in batches with
`ON CONFLICT DO NOTHING`, so a repeated backfill costs nothing.

The retry schedule lives on the row: `next_attempt_at` and `attempts`. The integration service
acknowledges bus messages at once after writing rows, then a loop picks due rows and attempts
them with exponential backoff from 30 seconds to six hours, thirty attempts in about three days,
after which the row is failed and can be retried by hand. Within one cycle, the first transient
failure of an integration ends that integration's share of the cycle, so an unreachable target
receives one request per cycle rather than hundreds.

Gundi identities: the Smart Parks entity is the Gundi source, so an EarthRanger track survives
a collar swap; the device travels in the observation's `additional` block.

## Consequences

- Replays, backfills and re-delivered bus messages cannot duplicate an object at a target.
- The delivery log is the audit: request, response, attempts, external id and a processing
  trace per row.
- Bus consumer lag never reflects a target outage; the queued count per integration does.
- A target that deduplicates on its own (a webhook receiver) can use `X-Protect-Delivery`.
- Gundi does not return stable EarthRanger ids, so updates and deletes of sent objects stay out
  of scope until a direct EarthRanger connector exists (risk register).
