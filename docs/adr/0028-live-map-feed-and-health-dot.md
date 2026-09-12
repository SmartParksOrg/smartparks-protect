# 0028. The live map's feed, unread as a seen-up-to time per person, and a health dot slow to worry

Date: 2026-09-12

Status: accepted

## Context

A person with the live map open learned about an alert from the Alerts page, one click away, and about events from the layers panel's Events tab, which is a layer switch rather than an inbox. Nothing on any page said whether the system itself was well: the System health page is for server admins, and a ranger had no way to tell a quiet night from a stalled pipeline.

## Decision

The live map gets a Feed button under Layers (decision D177): the panel lists the project's newest events with their alert state, one list for rule alerts and every other event, the same items the Events page shows; system notices stay on the server admin pages. Unread is per person (decision D178): the user's preference `feed_seen` keeps, per project scope, the creation time of the newest item seen; the badge counts newer items, opening the panel moves the mark, a first visit starts at the newest item so nobody meets a badge of 99 on day one, and alerts keep their own open, acknowledged and resolved state on top. A row centres the map on the event and opens its detail (decision D179); an open alert can be acknowledged from its row. The stream's `event.created` and `alert.created` refresh the feed and the badge, and an `alert.created` while the map is open shows a toast with a Show action; events stay silent and nothing makes a sound (decision D180). Every signed-in account also carries a small health dot in the top right corner (decision D181), fed by `GET /system/status`: green while every worker reported within the stale window and no system alert is open; amber once a worker has been silent past the window or a system alert has stayed open over 30 minutes; red only after two polls in a row without an answer from the server; a click names the reason and server admins get the way to System health.

## Alternatives considered

- Unread as the project's open alerts: no per-person state, but one person's acknowledge clears everyone's badge, and events could never be unread.
- A feed of alerts only: the detections, geofence and battery events are what a ranger reads the map for; the alert state rides on the same rows.
- A health dot on open system alerts alone, or one that turns amber at the first missed heartbeat: a reassurance that flickers is an alarm; the thresholds keep a hiccup from worrying a ranger.
- Sound for critical alerts: browsers block sound until the person interacted with the page, so it needs an opt-in; it can come later.

## Consequences

The map tells what happened without a page visit, and the badge is honest per phone. The preference document grows by one small map per project; the feed reads the newest 100 events per minute and on every stream message. The health dot is the first thing a ranger sees about the system, so a persistent amber is a real finding for a server admin, and the System health page is one click away for them.
