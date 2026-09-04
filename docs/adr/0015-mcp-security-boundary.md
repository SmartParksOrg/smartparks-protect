# ADR 0015: the MCP server is a resource server behind the API's OAuth 2.1

- Status: accepted
- Date: 2026-09-04
- Decisions: D68, D69, D70, D71

## Context

Architecture 27 asks for an MCP server above the normal API: no direct database access, the
user's own permissions, an AI action policy, audit and traceability, and interoperability with
Claude and ChatGPT. Both clients require OAuth 2.1 with PKCE, discovery through protected
resource and authorization server metadata, and client registration by client id metadata
document or dynamic registration.

## Decision

The API is the authorization server. It mounts the MCP SDK's authorize, token, registration
and revocation handlers under `/api/v1/oauth` with a database-backed provider and serves the
RFC 8414 metadata at the well-known path of the public URL. Consent is a page in the web
application. Clients register with a client id metadata document (preferred by Claude and
ChatGPT, no per-client rows beyond a cache) or dynamically; both must use HTTPS or loopback
redirect URIs, and a metadata document may only redirect to its own host.

Access tokens are JWTs signed with the existing `JWT_SECRET`, with the MCP URL as audience,
the user as subject, and the client id and scopes as claims. The MCP service verifies them
locally and calls the API with the same bearer. The API admits that audience only through a
middleware that allows `GET` requests on the paths the granted scopes cover, refuses everything
else with `insufficient_scope`, and writes one audit row per request with the tool name. The
JWT strategy accepts the MCP audience only for a request the middleware admitted, so no other
entry point can be reached with such a token. Refresh tokens are stored hashed, rotated on
every use, and revoked from the connections page.

Phase 9 exposes read scopes only; every write class of the AI action policy is disabled.

## Alternatives

- The MCP service as its own authorization server with the SDK's built-in routes: needs
  database access from the MCP service, which 27.1 forbids.
- Opaque tokens with an introspection endpoint: instant revocation, but a round trip per
  request and one more endpoint; a one-hour access token with revocable refresh tokens is
  enough for a read-only proof of concept.
- Hand-written OAuth endpoints: more code to get right than reusing the SDK's handlers, which
  already implement PKCE, the token request shapes and the registration rules.

## Consequences

- One authorization model: the same user, roles and permissions decide what an AI client sees.
- The MCP spec forbids passing a client's token to an upstream API that treats it as its own.
  Here the API is the issuer and admits the MCP audience deliberately, under a stricter policy
  than a session token, so there is no confused deputy; this is stated here rather than
  implied.
- The `mcp` package becomes a dependency of the API for its OAuth handlers.
- Write tools (phase 13) need new scopes, a confirmation flow and a policy table; the
  middleware is where the policy grows.
