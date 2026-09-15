# 0032. Attribution repair as a background job with progress

Date: 2026-09-15

Status: accepted

## Context

When an assignment changes (a start moved back to the device's first data, a device assigned to a project or an entity, a handover, "Recompute attribution"), the records already inside the range get their project and entity again from the assignments as they stand (decision D103). Until now that rewrite ran inside the request. On the development server a collar with 195,756 records took 38 s for the project extension and 60 s for the entity assignment; the proxy closes a request after 120 s and the API's connections carry a statement timeout of 120 s (decision D147). A collar with two or three years of history breaks the request, and meanwhile the page showed a greyed button and nothing else, so the person did not know the work was running or that it could take a while.

## Decision

An assignment change writes the assignment and queues one attribution job row (`attribution_jobs`, decision D206), then returns. The export service, already the batch worker for the curation jobs, runs the job: the window in pieces of thirty days, one transaction each, the records done so far written to the row after every piece, the current state of the device and the entities involved recomputed once at the end, a trace of its own. The assignment endpoints answer the job, `GET /devices/{id}/attribution-jobs` lists a device's newest jobs, and the device and entity pages poll it every three seconds while one is queued or running, drawing a callout with the records done, the percentage and a bar, and a toast when it finishes.

While a device's job runs, its other assignment changes are refused (409) and the pages disable those buttons, so two rewrites never race over the same rows. A change made while the job is still queued folds into it: the job reads the assignments when it starts, and its window widens to cover the new change, so the assign dialog's two steps (a project, then an entity) and a quick correction need no second job. A window without records queues nothing.

## Alternatives considered

- Keep the rewrite in the request and show a spinner and a toast: quick, but the request path stays bounded by the proxy and the statement timeout, so a long history fails whatever the page shows.
- Queue every change as its own job and run them in order: simpler rules, but several bars on one page and a second rewrite over rows the first one is still touching.
- A curation job with a new transformation: the machinery exists (batches, progress, a page), but curation jobs are corrections of values with an approval flow, and a reattribution is neither.

## Consequences

The records appear under their project and entity a little later than the click; the page says so and shows how far it is. The assignment endpoints no longer answer the counts of rewritten rows; the job carries them. A deploy while a job runs is safe: the bus redelivers the message and the worker restarts the job, whose rewrite is idempotent. The export service must run for the records to follow an assignment change; without it the row stays queued and the page says the records are waiting.
