# Cordis V2 scoped WebSocket chat admission

The production WebSocket stream now prepares and acquires the persisted conversation's scoped runtime before invoking the Agent turn service. It no longer inherits the process ROOT generation at this boundary.

MessageContext receives the application-owned scoped manager from the authenticated WebSocket app and retains it when a detached task opens a fresh database session. The new admission helper queries persisted conversation ownership, tenant/project ancestry, UserTenant and UserProject membership. It uses Conversation.id as the SESSION identifier, never the connection ID. Workspace-linked conversations request the additional workspace prompt-context service explicitly.

After authorization, the helper initializes missing private configuration and publishes its exact source. NACK is rejected. Membership is checked again after preparation's potential network waits, then the coordinator admits a reservation only after its durable receipt gates. Missing manager or pending receipt does not fall back to ROOT. The complete stream consumes the reservation through the scoped boundary, including existing DB, identity and metadata services. The boundary releases its lease on completion or cancellation.

Existing duplicate-message ACK and client-turn claim behavior remain ahead of preparation. Control, subscription and HITL boundaries are unchanged in this batch and remain separate migration work; this is not evidence that all consumers have moved to scoped authority.

## Evidence

- Entire WebSocket unit directory: 125 passed, 21 warnings, 36.67 seconds.
- Real SQL admission tests cover foreign user/tenant/project/session, project ancestry, missing membership, revocation during prepare, missing manager, NACK and receipt failure.
- An integrated test uses real persisted configuration initialization, production Bundle verification/Loader, publication and receipt, then obtains a scoped reservation with actual registered tools. Only external graph construction is replaced with a typed unavailable provider; no model or network provider operation is claimed.
- Generation tests use actual scoped registries and reservations to prove that neither an outer ROOT generation nor its replacement supplies the scoped turn resolver/distribution. They verify DB/identity/metadata and cancellation release.
- Ruff passes. Pyright reports zero errors and one pre-existing implicit-string-concatenation warning in router.py; the new helper/test have zero errors and warnings.

GitNexus impact reported 3 upstream relationships for the stream boundary and 8 for Context.with_db, both LOW. New helper modules may be absent from its index; graph results do not substitute for the runtime and SQL tests.

## Remaining acceptance

No actual LLM conversation or native Electron session was executed in this batch. Workspace-linked preparation still requires the production workspace prompt-context provider to be enabled and owned correctly. WorkspaceCore and other event consumers, concurrent governance fencing, historical migration recovery, V1 retirement and final native acceptance remain open. Post-prepare membership checking is a point-in-time recheck, not a transactional fence against all later revocations.

Generator and contract completeness checks passed. Logs and SHA-256 checksums: `/var/tmp/cordis-scoped-chat-0eqj8fuw`.
