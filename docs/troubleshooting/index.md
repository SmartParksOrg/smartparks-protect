# Troubleshooting

Where to look when something does not arrive, does not fire or does not send. Start in the application: System health, Needs attention and the Trace explorer answer most questions without a shell.

## A device stopped updating

1. Server admin, System health. Is a worker stale, is there stream lag, are there dead letters? A stale decoder means nothing is decoded; fix the worker first (`docker compose logs decoder`).
2. Server admin, Data sources: does the source show events in the last hour? If not, the platform is not delivering: check its console with the deep link on the device page, the webhook URL and token for push sources, the credentials for MQTT and websocket sources (`docker compose logs ingest` shows reconnects and refusals).
3. Project, Network, Traffic: are uplinks of the device arriving? If they arrive but the device page stays old, open the trace of the newest uplink.
4. The trace says where it stopped: `PAYLOAD_DECODE_FAILED` (the driver rejected the frame: wrong device type, wrong port, firmware change), `DEVICE_NOT_FOUND` or an unassigned status (no device for the identity: Needs attention, unknown identities), `TIMESTAMP_INVALID` (the device clock), a duplicate (the same record arrived over another path, which is fine).
5. No trace at all for a DevEUI that the network shows as active: the identity belongs to another data source or is ignored (Needs attention).

An AI client connected through MCP can run this investigation with the `investigate_missing_data` prompt.

## A rule did not fire

Rules, open the rule, Test: replay the last hours against the saved version and read the verdicts. A rule with an evaluation error shows it on the list and on System health under Rules and automation; the error is on the rule row. Remember FOR durations, cooldowns and that geofence rules need the entity to have been outside before it is inside.

## A notification or integration did not send

Automations show every delivery with its response; integrations show every delivery with request, response and trace. A transient failure is retried on the schedule of the row; a permanent one needs a fix and a manual retry. Email needs `MAIL_*` configured and, outside production, the recipient in `DEV_NOTIFY_EMAILS`; Telegram needs the chat linked with `/start <code>`.

## Backups

Server admin, Backup and recovery shows each item with the reason it is not green. The runs table has the error of a failed job; the full output is in `logs/backup.log` on the server.

- **WAL archive stale or failing.** `docker compose exec postgres protect-pgbackrest --stanza=protect check` tests the repository from the database container. A wrong endpoint, bucket, key or passphrase shows here. After fixing `.env` (through the host vars and `--tags sync-config`) restart the stack; PostgreSQL retries the segment that failed.
- **Stanza missing.** After a fresh deployment run `docker compose exec postgres protect-pgbackrest --stanza=protect stanza-create` once, then a full backup.
- **Object mirror fails.** The `object-mirror` container prints which bucket failed; run `docker compose --profile backup run --rm object-mirror` by hand to see it. Check that the key may write to the bucket and that the endpoint uses TLS unless `BACKUP_S3_SECURE=false`.
- **Integrity check fails.** Objects the database references are not in the backup bucket. Usually the mirror has not run since they were written: run it, then the check. Objects that were deleted from MinIO on purpose need their database rows cleaned up.
- **Restore test fails.** `logs/restore-verify.log` names the step. Disk space (twice the database), a wrong passphrase, or a backup taken with a different PostgreSQL major version are the usual causes.

## Telemetry

No spans in Grafana: `OTEL_EXPORTER_OTLP_ENDPOINT` must be reachable from inside the containers (`http://lgtm:4318` with the profile, not `localhost`), and the services must have restarted after the change. The API logs `telemetry enabled` at start when it exports.

## AI clients

The connection fails before the consent page: the client could not discover the authorization server. The MCP URL must be exactly `<PUBLIC_URL>/mcp` over HTTPS, and `/.well-known/oauth-authorization-server` on the public URL must answer (it is served by the API through nginx). The consent page opens but the client reports an error afterwards: the redirect URI is not registered or the code expired (`OAUTH_CODE_LIFETIME_SECONDS`). A tool answers 403: the user lacks the project or the token lacks the scope; reconnect the client. Every request is in the audit log under actor `mcp`.

## Reading the logs

`docker compose logs -f <service>` follows one service. Every line is JSON with `service`, `trace_id` and `request_id`; the request id of an API call is in the `X-Request-ID` response header, so an error a user reports can be found with `docker compose logs api | grep <request id>`. `scripts/verify-server.sh` is the read-only pass or fail check after an update or a restore.

## ChirpStack's Test connection answers "HTTP 400 instead of gRPC"

The call reached the nginx in front of ChirpStack, but a plain `proxy_pass` location handed
it to ChirpStack over HTTP/1.1, which answers an empty 400 to gRPC framing. The `grpc_pass`
location from the [ChirpStack page](../integrations/chirpstack/index.md#connecting-an-existing-chirpstack)
is missing, sits in another server block (port 80 instead of 443), or nginx was not
reloaded after adding it (`nginx -t && systemctl reload nginx`). A quick check from the
Protect server: `curl -sk --http2 -X POST -H "content-type: application/grpc" https://<host>/api.TenantService/List -D -`
answers `content-type: application/grpc` with a `grpc-status` header once the location
works, and an empty `HTTP/2 400` while it does not; a `403` means the location works but
its `allow` line does not name the Protect server's address.

## A platform is connected but nothing shows

Server admin, Traffic (or Data sources, Traffic for one source) lists every message received in the last hours, linked to a device or not, with the raw payload and the processing status. Empty means the platform never posted: check its own integration log. Rows with an unknown identity mean the DevEUI is not linked yet: accept it from Needs attention.
