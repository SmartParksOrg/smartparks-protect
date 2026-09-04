# MCP: AI clients

Smart Parks Protect exposes a read-only [Model Context Protocol](https://modelcontextprotocol.io) server so that Claude, ChatGPT and other MCP clients can answer questions about a project's entities, devices, positions, measurements, events and processing traces. This is the proof of concept of architecture section 27 (phase 9). Every request an AI client makes runs as the user who connected it, within the permissions of that user, read only, and lands in the audit log.

## How it fits together

| Part | Where | Role |
| --- | --- | --- |
| MCP server | `services/mcp`, container `protect-mcp`, URL `<PUBLIC_URL>/mcp` | Streamable HTTP endpoint with tools, resources and prompts. Verifies access tokens and calls the API with them. Never touches the database. |
| Authorization server | The API, `/.well-known/oauth-authorization-server` and `/api/v1/oauth/*` | OAuth 2.1 with PKCE, client registration by metadata document or dynamic registration, consent, token issue and refresh. |
| Consent and connections | The web application, `/oauth/consent` and `/account/connections` | The user approves a client and can disconnect it later. |

The MCP server is a resource server in OAuth terms: it publishes protected resource metadata at `/.well-known/oauth-protected-resource` (and the path-suffixed variant), answers 401 with a `WWW-Authenticate` challenge that points there, and requires every read scope on every request.

## Connecting a client

The server must be reachable from the client's network over HTTPS (Claude and ChatGPT connect from their own infrastructure, see the [deployment guide](../getting-started/deployment.md)). The MCP URL is the public URL of the server plus `/mcp`, for example `https://protect.example.org/mcp`.

- **Claude (web, desktop, mobile, Cowork).** Customize, Connectors, Add custom connector, paste the URL. Leave the client id and secret empty. Claude identifies itself with its client id metadata document; the consent page shows `claude.ai` as the client.
- **Claude Code.** `claude mcp add --transport http protect https://protect.example.org/mcp`, then `/mcp` to sign in. Claude Code redirects to a loopback port on your machine; the consent page warns about that.
- **ChatGPT.** Settings, Connectors (developer mode), add the URL. ChatGPT identifies itself with its client id metadata document. Deep research uses the `search` and `fetch` tools.
- **MCP inspector.** `npx @modelcontextprotocol/inspector`, connect to `http://localhost:8001/mcp` on a development machine. The inspector registers dynamically and runs in a browser, so add `http://localhost:6274` to `CORS_ORIGINS`.

On the first connection the client opens the consent page in a browser. Sign in, check the client and the scopes, and choose Allow. The client receives an access token that lives one hour and a refresh token that lives thirty days and is rotated on every use.

## What a client can do

Tools, all read-only and bounded:

| Tool | Reads |
| --- | --- |
| `list_projects` | The user's projects and roles; the starting point |
| `search_entities` | Entities of a project by name, type or status (at most 100) |
| `get_entity` | One entity with its type, current device, assignment history and latest position |
| `get_device` | One device with type, assignments, external identities and deep links |
| `get_latest_position` | The newest position of an entity or device |
| `query_measurements` | Aggregated measurements per metric and entity (the Data Explorer's series endpoint, at most five metrics per call) |
| `list_metrics` | Metric keys with data in the project |
| `query_events` | Events with alert status, newest first (at most 100) |
| `get_processing_trace` | One processing trace with its steps and error |
| `search_traces` | Traces of a project's devices, filtered by device, identity, status or error code |
| `search`, `fetch` | The generic pair ChatGPT expects: search entities and devices by name, fetch any `smartparks://` record |

Resources: `smartparks://projects/{id}`, `smartparks://projects/{id}/entities/{id}`, `smartparks://projects/{id}/events/{id}`, `smartparks://devices/{id}`, `smartparks://traces/{id}`. Entities and events carry the project in the URI because the API is project scoped.

Prompts: `analyze_device_health` and `investigate_missing_data` guide a client through the tools for the two questions rangers ask most.

Writes, device control and rule changes are not exposed. The AI action policy of this release is: read allowed, everything else disabled. Write tools arrive in phase 13 with their own scopes and confirmation flows.

## Authentication in detail

Scopes: `projects:read`, `entities:read`, `devices:read`, `positions:read`, `measurements:read`, `events:read`, `traces:read`, plus `offline_access` for a refresh token. The MCP server requires all read scopes; a token with fewer gets a 403 with `insufficient_scope` and the client asks the user to re-consent.

Access tokens are JWTs signed with the server's `JWT_SECRET`, with the MCP URL as audience, the user as subject, the client id and the scopes as claims, valid for `JWT_LIFETIME_SECONDS`. The API accepts them only for `GET` requests on the paths a scope covers (`protect_api/oauth/scopes.py`); any other request is refused with 403. A session token from the web application is never accepted by the MCP server, and an MCP token cannot do anything a session token can outside its scopes.

Client registration: the authorization server advertises `client_id_metadata_document_supported` and a registration endpoint. A client whose id is an HTTPS URL is fetched from that URL, must be self-referential, and may only redirect to its own host or a loopback address. Dynamically registered clients must redirect to HTTPS or loopback URIs. Loopback redirect URIs match with the port ignored (RFC 8252), which native clients need.

Every API request made through the MCP server writes an audit row (`mcp.request`) with the user, the client id, the tool name, the path and the response status. Server admins see them in the audit log filtered on actor `mcp`.

Disconnecting: Connected AI clients in the sidebar lists the clients a user has authorized; Disconnect revokes their refresh tokens. The running access token expires within the hour. A password change also invalidates every token issued before it.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `MCP_PUBLIC_URL` | `PUBLIC_URL` + `/mcp` | The canonical MCP URL and token audience. Set only when the MCP server has its own host name. |
| `MCP_PORT` | `8001` | Host port of the container on a development machine |
| `API_INTERNAL_URL` | `http://api:8000` in compose | Where the MCP service reaches the API |
| `OAUTH_CONSENT_LIFETIME_SECONDS` | `600` | How long a consent request stays valid |
| `OAUTH_CODE_LIFETIME_SECONDS` | `300` | Lifetime of an authorization code |
| `OAUTH_REFRESH_TOKEN_LIFETIME_DAYS` | `30` | Lifetime of a refresh token |

nginx routes `/mcp` and `/.well-known/oauth-protected-resource` to the MCP service and `/.well-known/oauth-authorization-server` to the API, with a rate limit of 300 requests per minute per address on `/mcp`.

## Limits

- Tool results are bounded by row limits and time windows; ask for narrower windows rather than more rows. Large extracts belong in an export job, which a later release exposes as a tool.
- Claude accepts tool results up to about 150,000 characters and waits at most five minutes per call.
- The MCP server is stateless: any replica can answer any request, and no session state is kept between calls.

## Verification status

Verified locally with the test suite (`tests/mcp`, `tests/api/test_oauth.py`) and against the local stack. The exit criterion of phase 9, Claude and ChatGPT answering "Why has device X stopped updating?" against the dev server, waits for the dev server (a public HTTPS endpoint). The result is recorded in `PROJECT_PLAN.md` when it is done.
