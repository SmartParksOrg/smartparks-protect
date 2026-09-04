# Notifications

Notification channels, targets and their configuration are described with the automations: [automations and notifications](../rules/automations.md).

Environment variables:

| Variable | Purpose |
| --- | --- |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM` | SMTP for email notifications and auth mail. Port 465 uses TLS, every other port STARTTLS |
| `DEV_NOTIFY_EMAILS` | On non-production servers, the only addresses that receive mail |
| `TELEGRAM_BOT_TOKEN` | The installation's bot. Empty disables Telegram |
| `RULES_RELOAD_SECONDS` | How often the rules service re-reads enabled rules (default 10) |
| `SYSTEM_CHECK_INTERVAL_SECONDS` | Interval of the worker, lag and dead-letter checks (default 300) |
