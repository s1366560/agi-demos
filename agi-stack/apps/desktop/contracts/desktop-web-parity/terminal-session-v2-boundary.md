# Terminal Session V2 authority boundary

Terminal Session V2 remains unavailable until the cloud service can resolve and
verify the canonical tenant, project, conversation, run revision, and execution
environment for the authenticated caller. A project-scoped PTY registry or a
working WebSocket transport does not satisfy this authority requirement.

Cloud capability responses use these stable reason codes:

- `terminal_interactive_canonical_run_authority_unavailable`: the legacy
  project-scoped terminal may exist, but it is degraded because it cannot be
  bound to a canonical run and environment.
- `terminal_session_v2_canonical_run_authority_unavailable`: create and resume
  are unavailable because the service cannot safely mint or validate a
  scope-bound resume token.

Desktop must not probe the legacy cloud terminal route when either reason is
declared. Local mode keeps its native workspace terminal compatibility path;
that path is an explicit `native_workspace` equivalent and does not claim an
isolated or resumable cloud sandbox.

The V2 capability can become available only after the service, not the
renderer, resolves all scope fields, rejects stale run revisions, stores the
session with a bounded TTL, and validates a server-minted resume token on every
resume and WebSocket attach.
