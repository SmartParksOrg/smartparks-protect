"""OAuth 2.1 authorization server for AI clients (architecture 27.5, decisions D68 to D71).

The endpoints `/api/v1/oauth/{authorize,token,register,revoke}` are the MCP SDK's handlers
bound to `ProtectAuthorizationServerProvider`, which keeps clients, codes and refresh tokens in
the database and mints JWT access tokens (`shared.oauth`). The consent screen is the frontend
page `/oauth/consent`; it approves or denies through `routes.oauth_router`.
"""
