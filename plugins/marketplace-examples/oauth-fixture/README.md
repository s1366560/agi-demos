# Local OAuth acceptance fixture

Run `python3 plugins/marketplace-examples/oauth-fixture/server.py` from the repository root.
The standard-library server binds only `127.0.0.1:18891`; it is a test service, not a production identity provider.
Use `--token-ttl 5` for short-expiry refresh tests (default 30 seconds).

Set `PLUGIN_MARKETPLACE_OAUTH_TEST_ORIGIN=http://127.0.0.1:18891` only in the backend's explicit test/development mode. Production must reject this override. Import `plugin/` locally or point the curated test catalog configuration to this directory. The fixture is deliberately excluded from the public curated catalog.

The consent page shows its test credentials: username `fixture-user`, password `fixture-password`.
Pre-registered public client: `marketplace-fixture`; its callback must be a loopback HTTP URL ending in `/callback` (any local port). DCR accepts explicitly registered loopback callback URLs. Client authentication is `none`.

Discovery endpoints:

- `/.well-known/oauth-protected-resource/mcp` and `/.well-known/oauth-protected-resource`
- `/.well-known/oauth-authorization-server`
- `/authorize`, `/token`, `/register`, `/revoke`
- Resource: `http://127.0.0.1:18891/mcp`

Authorization requires S256 PKCE, state, the exact resource URL and scope `mcp:tools`.
Codes are single-use and expire after 60 seconds; refresh tokens rotate and expire after ten minutes.
Invalid verifier, code replay, changed resource, wrong client and expired credentials are rejected.
Deny consent returns `access_denied` with original state. Client-side cancellation must reject a later callback.
MCP echo and HTML app resources require a valid access token; no credential material is logged.

Run fixture tests with `python3 -m unittest discover -s plugins/marketplace-examples/oauth-fixture -p 'test_*.py'`.
