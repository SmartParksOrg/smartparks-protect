# ADR 0019: AI clients write through one policy-gated endpoint

- Status: accepted
- Date: 2026-09-04
- Decisions: D87

## Context

Architecture 27.4 introduces write and action tools for AI clients by impact class, and 27.6
an AI action policy on top of RBAC that lets an organisation decide which classes are open,
need confirmation or are off, even where the person has the permission. Phase 9 made the API
refuse every non-GET request from an MCP token. MCP servers with streamable HTTP run stateless,
so a confirmation cannot live in the server's memory.

## Decision

**One endpoint.** An MCP token may write only through `POST /api/v1/mcp/actions` and its
`confirm` call. The endpoint knows the action classes, checks the client's write scope
(`events:write`, `alerts:write`, `devices:control`) and the person's permission, applies the
server-wide policy and then executes the action through the frameworks people use: the manual
event path, alert acknowledgement, `request_command` with the MCP actor. Nothing else on the
API accepts a write from an MCP token.

**Confirmation as data.** A proposal the policy holds becomes a `mcp_pending_actions` row
with a summary and a ten minute expiry; `confirm_action` executes it for the same person and
client. The MCP tools return the summary with an instruction to ask the person first.

**Policy as a server setting.** `server_settings.ai_action_policy` holds a mode per action;
server admins edit it on the AI clients policy page. Defaults: confirmation for every action,
high-impact control disabled and not configurable in this version.

**Scopes.** Write scopes exist next to the read scopes; a client that requests no scopes is
offered all of them on the consent page, where the person decides.

## Consequences

- No alternative control path: the audit log, traces, command lifecycle and event pipeline
  see an AI write exactly as a person's, with the MCP actor and the client id.
- The policy is global, not per project; a per-project override can come later without
  changing the endpoint.
- Confirmation depends on the AI client honouring the instruction to ask; the ten minute
  expiry, the same-client rule and the audit rows limit the damage of a client that does not.
