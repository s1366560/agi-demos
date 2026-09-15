# Local signed WASM plugins (protocol V2)

Local packages use the sidecar's existing generation publisher and application SQLite store.
They do not create or modify cloud marketplace records or ROOT publications.

The host operator configures `AGISTACK_LOCAL_PLUGIN_TRUSTED_KEYS_FILE` before starting the
canonical native client with `make -C agi-stack run-desktop`. Its value is the path to a public
trust configuration, read once at sidecar startup:

```json
{"schema_version":1,"public_keys_pem":["-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"]}
```

Only Ed25519 SPKI public keys are supported. A package request cannot add a trust anchor.
Changing configured trust requires restarting the native client. No private signing key belongs
in this file. An absent or invalid trust configuration prevents external package import.

The native file picker selects a `.mspkg` ZIP, at most 64 MiB. The sidecar's authenticated API is:

- `GET /api/v1/local-plugins/v2/installations?tenant_id=...&project_id=...`
- `POST /api/v1/local-plugins/v2/installations/inspect`, with tenant/project IDs and `archive_base64`.
- `POST /api/v1/local-plugins/v2/installations/import`, adding the inspected exact `reference` and
  explicitly approved `approved_permissions`.
- `POST /api/v1/local-plugins/v2/installations/{bundle_id}/{enable|disable|revoke|uninstall}`,
  with tenant/project IDs and the exact `reference`.

Inspection verifies the descriptor, signature, provenance reference, permission declarations,
artifact inventory and bytes. It does not persist an installation or grant runtime permission.
The inspected source coordinate is `local-file://{bundle_id}/{version}`; its digest is the
protocol's canonical **bundle manifest digest**, not a ZIP-file hash. Installation requires
approval of all declared permissions and a current project manager. The final approval and write
share the application-store connection lock and recheck session, project, tenant and manager role.
Only inspect/import have the larger JSON body limit needed for base64 transport.

Installation and re-enabling compile the actual artifact using the production Loader before
committing. Local support currently admits standalone `desktop-sidecar` WASM modules providing
exactly `service:wasm-tool-set@1.0.0`, without host imports or injected service dependencies.
The score contract is documented in [plugin-wasm-score-abi-v1.md](plugin-wasm-score-abi-v1.md).
A Python-only bundle does not establish Local executable capability.

Each installation is narrowed to its approved project and receives an isolated service coordinate.
The package identity, signed plugin/module identity, artifact digest and original tool name remain
frozen. Model tool names are deterministic `plugin__` names derived from the isolated entry;
the definition retains the signed package and original tool names in its description.

Stored archive bytes are reverified on generation activation and execution authorization. Changes
wake the existing reconciler. An active generation remains available if a replacement fails;
current installation and scope checks still prevent a revoked or damaged plugin from executing.
If no Local generation exists at startup, an external failure leaves the independently validated
builtin baseline available so the package can still be removed. The failed external module is not
published. Each list item carries `activation_status` (`pending`, `active`, `failed`, `inactive`)
and `activation_error` (a nonempty string only for `failed`, otherwise null); configured enablement
is distinct from actual activation. Removing the last external package clears an external trust
failure without requiring a functioning signer configuration.
Disable preserves approvals, revoke records an explicit revoked state and clears approvals, and
uninstall deletes the scoped record. Re-enabling a revoked package requires a new approved import.
A retained callback checks the current session, native operation, generation, installation and grants.
An independent close owner releases the generation lease even when the calling async task is aborted.

Build execution requires a real DesktopRun, approved execution environment, and an authorized tool
invocation. Plan execution instead binds the captured native HTTP message identity and the exact
active conversation control handle. Both HTTP messages and WebSocket `send_message` capture the
authenticated connection identity and scope it around their spawned turn. Only the verified factory's explicit Read metadata can extend
the Plan tool roster. Another message, changed session, cancellation or a replaced control handle
invalidates the operation; no synthetic Build approval is created.

Delegated Subagents have independently constructed plugin hosts. Their actual execution id,
Subagent id, parent run revision and registered live child control must all match the child execution
context. A parent host cannot execute inside that context, and a child host cannot execute in its
parent or sibling context. The existing Agent/Skill/Subagent tool intersection and parent approved
run ledger remain in force. Only verified Read metadata can narrow the conservative delegated effect.
Installation approvals are rechecked at exposure and execution for all three operation kinds.
Authenticated queued-input promotion, paused/unstarted resume, HITL answers, recovery forks, and
run/artifact review continuations capture the identity from that new verified request. Build
continuations bind the post-transition run; Plan continuations bind the new message and control.
Neither a previously captured parent task context nor a serialized archive verification proof is
reused as new authority. Session invalidation after catalog delivery still prevents tool dispatch.

Persisted plugin call payloads use metadata captured from the exact verified execution host after
Agent/Skill/profile filtering. The timeline redactor checks that host's live operation, installation
approval and generation, then combines standard sensitive fields with the tool's declared fields.
Unknown aliases, excluded tools and expired captures remain unavailable; a `plugin__` name alone
never grants permission to publish a payload.

Child engines persist `subagent_tool_call`, `subagent_tool_result`, and `subagent_tool_error`
events independently of the parent `act`/`observe` stream. Each payload carries the real child
`execution_id` (also `run_id`, matching child lifecycle events), `parent_run_id`,
`parent_run_revision`, `subagent_id`, `round`, `tool_name`, redacted `tool_input`, and `failed`.
Results add redacted `tool_output`; errors add an opaque `error`. They carry no top-level
`toolName` and do not increment parent tool counters. The observer checks the live child task
identity, native session, parent revision and registered child control before publication, and
uses only the final child's tool permissions and its own verified plugin host metadata.

The successful `subagent` tool response also returns its real `execution_id`, parent DesktopRun
`run_id`, and `run_revision`; no identifier is inferred from the child's answer.

Local agents discover the managed skill library with the read-only `skill_list {}` tool and load
instructions through `skill_loader {"skill_id":"..."}` or an exact, unambiguous `name`.
Both tools enforce the current native operation and the captured/current Agent and SubAgent
skill rosters. They read only active resources in the current tenant/project. A load reports
declared tools and currently advertised tools separately, with `execution_started: false` and
`authority_changed: false`. It does not change an explicit Skills chip binding, start a skill,
grant tool permissions, or claim execution succeeded. Model selection is a structured tool call;
there is no keyword-based skill routing. Ordinary tool invocation retains the reviewed run,
profile intersection, plugin signature and installation approval checks.

The developer QA fixture exporter uses the same real signed fixture and production import/runtime
path as the integration tests. It generates a fresh in-memory signing key and writes only the
signed package, public key, public trust JSON and non-secret metadata:

```sh
AGISTACK_LOCAL_WASM_FIXTURE_OUTPUT="$PWD/artifacts/local-wasm-fixture" \
  cargo test --manifest-path agi-stack/Cargo.toml -p agistack-desktop-sidecar \
  --bin agistack-desktop-sidecar export_verified_local_wasm_qa_fixture --locked -- --ignored
```

The export test verifies the emitted package through authenticated import, the production generation,
and `AuthorizedRunToolHost` before writing it. It does not install anything in the running client.
