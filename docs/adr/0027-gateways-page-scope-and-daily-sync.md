# 0027. The Gateways page shows a project's whole network, and the gateway list is synced daily

Date: 2026-09-12

Status: accepted

## Context

The Gateways page listed the gateways that had received the project's devices in the chosen window, busiest first. A gateway of the same network that heard none of the project's devices stayed off the page, so a ranger could not see that a mast was up, and Tim missed one on 2026-09-12. Names and platform locations came from a sync button on the data source that nobody pressed, and the sync crashed on gateway rows created from receptions in the same run.

## Decision

The Gateways page lists every gateway of the data sources the project's devices have an identity on (decision D175): the ones that heard the project's devices in the window busiest first, then the silent ones by last seen, with a source filter in the URL and a footer counting the silent ones; the all-projects scope lists the whole registry. The gateway sync is shared code (`shared/connectivity/gateway_sync.py`, decision D176): the ingest service runs it two minutes after start and every 24 hours over every enabled source whose adapter lists gateways and whose API channel is on, committing per source and logging a failing one, and the button on a data source runs the same read for one source at once. The registry update merges stats and attributes from an empty document, since a row created earlier in the same session reads its column defaults as None until refreshed.

## Alternatives considered

- Keeping the page to hearing gateways with a note counting the silent ones: the note answers "how many" but not "which", and the mast that is up but silent is exactly the one to look at.
- A separate registry page for server admins: another page for the same rows, and rangers are project users.
- A scheduled sync in the API process: the ingest service already owns the platform connections and the polling schedule.

## Consequences

A project's Gateways page reads as a network map: what hears, what is silent, what is offline. A tenant API key that lists only part of a ChirpStack's gateways leaves the rest with their EUI as name, which the page shows as it is; a global key or the platform's admins fix that, not the sync. The daily pass costs one listing call per source per day.
