# Security

What protects a Smart Parks Protect server, what the audit of decision D94 checked, and what
it found. The [security policy](https://github.com/SmartParksOrg/smartparks-protect/blob/main/SECURITY.md)
says how to report a problem.

## Layers

| Layer | Mechanism | Where |
| --- | --- | --- |
| Host | Firewall (SSH, HTTP, HTTPS), SSH keys only with drift check, unattended security updates, fail2ban on SSH, daily security check published to System Health | Ansible roles `security`, `security-check` |
| Transport | TLS from Let's Encrypt, HTTP redirected, HSTS | nginx role |
| Edge throttling | nginx `limit_req` zones: API 600/min, login 20/min, ingest 3000/min, MCP 300/min per address | nginx template |
| Application throttling | Redis-backed windows that hold without nginx: login, registration, password reset and token calls 20/min per address; webhook posts 3000/min per data source; AI actions 60/min per address; 429 with `Retry-After` (`RATE_LIMIT_*` settings) | `protect_api/ratelimit.py`, `shared/ratelimit.py` |
| Authentication | Email and password with fastapi-users, JWT bearer tokens, invitation-only registration, password reset by email | `protect_api/auth` |
| Authorization | Server admin flag; per project one role (viewer, project admin) mapped to fine-grained permissions; every endpoint declares its dependency (`require_server_admin`, `require_permission`, `require_project_role`) | `protect_api/deps.py`, `shared/permissions.py` |
| AI clients | OAuth 2.1 with PKCE and dynamic registration; scopes per data class plus write scopes; an MCP token reaches read paths per scope and writes only through the AI action endpoint, under the server's AI action policy | `protect_api/oauth`, ADR 0015, ADR 0019 |
| Webhooks | Per data source bearer token, hashed at rest; token in the query only for platforms that cannot set a header | `routers/ingest.py` |
| Credentials at rest | Data source and integration credentials encrypted with Fernet under `CREDENTIALS_KEY`; write-only in the API (`has_credentials` is all a reader sees); never in exports | `shared/secrets.py` |
| Audit | Every write by a person or an AI client is an audit row with the actor, the request id and the client id | `protect_api/audit.py` |
| Secrets in the repository | A pre-commit hook refuses credentials; private configuration lives outside the repository | `.githooks/pre-commit`, installed by `scripts/dev.sh hooks` |

## The audit (2026-09-04, decision D94)

**Access matrix.** `tests/api/test_access_matrix.py` walks every operation of the OpenAPI
document (235 at the time) with four callers and fails when a class of caller gets through
where it must not:

| Caller | Expectation | Result |
| --- | --- | --- |
| Anonymous | 401 on everything except health, version, the auth flow and the webhook | holds |
| Viewer of another project | 403 on every project-scoped operation of the other project and on every server admin operation (admin, data sources, backups, catalogue writes) | holds |
| Viewer of the own project | 403 on every write except the viewer's own: manual events, alert acknowledgement and resolution, exports, saved views, the read-only rule test | holds after one fix (below) |
| AI client with read scopes | 403 on every non-GET outside the AI action endpoint | holds |

**Finding, fixed.** The curation endpoints for corrections and bulk jobs checked the
`data:curate` permission inside the handler, after the body was validated, so a viewer
received 422 for a malformed body instead of 403. The checks are route dependencies now, and
the matrix test would catch a recurrence.

**MCP scopes.** `tests/api/test_oauth.py` covers the consent flow, PKCE, refresh rotation and
revocation, missing scopes with the `WWW-Authenticate` challenge, and client id metadata;
`tests/mcp` covers the write tools against the policy. The scope rules are a small allowlist
of path patterns (`protect_api/oauth/scopes.py`); an unknown path is refused.

**Credential handling.** Reviewed: credentials are encrypted before they reach the database
and decrypted only in the workers that use them; the API never returns them; logs carry
request ids, not bodies; `CREDENTIALS_KEY` and `JWT_SECRET` come from the host vars and are
absent from the repository. Open point: rotation of `CREDENTIALS_KEY` re-encrypts nothing
today; a rotation procedure is a follow-up.

**Dependencies.** `pip-audit` over the locked Python dependencies and `npm audit` over the
frontend run in CI on every push and every Monday, failing on high or critical findings.
Both were clean at the audit.

**Rate limits.** Application-level throttling added (table above) so a server without nginx,
or nginx misconfigured, still refuses brute force on login and floods on the webhook.

## Operating notes

- Rotate a webhook token from the data source page; the old token stops at once.
- Rotate an AI client's access by revoking it under Connected AI clients; the refresh token
  dies with it.
- The daily security check reports on System Health under the security area; a failing check
  shows there until the next run passes.
- Keep servers on tagged releases and read the changelog's security notes before an update.
