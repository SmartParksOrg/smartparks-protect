# Automations and notifications

An automation is a configured reaction to events (architecture 16): which events, which actions. Actions are the concrete side effects: a notification to an email address or a Telegram chat, or a signed webhook. Integration forwarding and device commands arrive with phases 8 and 6 and use the same action list.

## Matching

| Field | Meaning |
| --- | --- |
| Event types | Only these types; empty means every type |
| Minimum severity | info, warning or critical and up |
| Only events with an alert | Skip events that created no alert |
| Entities, rules | Optional filters on the subject and the rule that produced the event |
| Skip events older than | The freshness bound. Events whose time is older than this when the automation runs are skipped and recorded as skipped, never acted on (architecture 25.8) |

Project automations react to the project's events. Server-level automations (Server admin, Automations) react to system events: stale workers, dead letters, consumer lag.

## Deliveries

Every action of every automation for one event is an action delivery with a status (queued, sent, failed, skipped), attempts, the response of the channel and a processing trace. The Deliveries tab lists them; a failed delivery can be retried, which republishes the event and reruns only the actions that did not succeed. A transient failure (SMTP down, a webhook answering 5xx, a timeout) is retried by the bus with backoff; a permanent one (an unlinked Telegram chat, a webhook answering 4xx) is not.

## Notification targets

A target is where a notification goes. Targets belong to a project (Project admin, Notifications) or to the server (Server admin, Notifications) and are used by automations of the same scope.

**Email** needs `MAIL_SERVER`, `MAIL_USERNAME`, `MAIL_PASSWORD` and `MAIL_FROM` in the environment. On a non-production server only addresses in `DEV_NOTIFY_EMAILS` receive mail; everything else is logged and the delivery is marked skipped, so a development server never mails real people.

**Telegram** uses one bot per installation (`TELEGRAM_BOT_TOKEN`, created with BotFather). A Telegram target gets a link code; from the chat or group that should receive alerts, send `/start <code>` to the bot, or open the `t.me` link the page shows. The automation service polls the bot, links the chat to the target and answers in the chat. Codes expire after 24 hours; Relink issues a new one.

Use Test on a target to send a test message; the result says sent, skipped (with the reason) or failed.

## Webhooks

A webhook action posts JSON to the URL with the event, the alert, the project, entity and device names and a link back. With a secret, the body is signed: `X-Protect-Signature: sha256=<hmac-sha256 of the body>`. Answers of 5xx are retried, 4xx are recorded as permanent failures, the first 500 characters of the response are stored on the delivery.

## System alerts

The rules service checks every five minutes (`SYSTEM_CHECK_INTERVAL_SECONDS`) whether a worker has not stamped its heartbeat for fifteen minutes, whether a dead-letter stream holds messages, and whether a consumer group is more than a thousand messages behind. Each finding opens one system alert (visible under Server admin, System alerts) and the alert resolves itself when the finding clears. A server-level automation with a server-level target turns these into email or Telegram messages. Note that the rules service runs the checks: when it is down itself, only the System health page shows it.
