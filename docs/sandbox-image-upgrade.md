# Sandbox image verification and safe rebuild

This is a code path and an operator procedure. It does not upgrade a running
sandbox, and it has not been applied to the R6 container.

`org.memstack.sandbox.source_digest` identifies container image source bytes.
It does not attest the tool server process that loaded modules for a call.
A path inside the container, including `/opt/sandbox-mcp-venv`, is an image
copy. Its mtime does not identify an MCP server running outside the container.
Runtime attestation has to name that loaded component. The call, transport,
process, and module evidence for R6 is pending and is not established here.

## What is executable now

1. Read the container label `org.memstack.sandbox.source_digest`.
2. Compare it with the digest of the sandbox source you intend to run.
   `image_status` returns `unknown` when either side is missing and `stale`
   when they differ. Unknown is not treated as current.
3. Before any automatic health rebuild, `MCPSandboxAdapter._attempt_sandbox_rebuild`
   calls `project_run_state`. That reads `agent_run_authorities` for
   `queued` or `running` rows and the in-process mark written by
   `_mark_root_run_authority_running` and `_settle_root_run_authority`.
   `active` and `unknown` both refuse the rebuild. A container with no
   `org.memstack.sandbox.active_run` label is not treated as idle.
4. `plan_image_migration` returns a plan only. `upgrade_performed` is false
   and `stage` is `plan_only`. It does not create a container.

## Operator procedure, not run from this repository automatically

1. Confirm `project_run_state` is `idle` for the project. If it is `unknown`,
   stop and repair the authority read before doing anything else.
2. Build the sandbox image from the intended source and record
   `fingerprint_sources` as `org.memstack.sandbox.source_digest`.
3. Keep the existing workspace directory and the project's permission mode.
   The plan copies those fields and sets `recreate_live_container` to false.
4. Only after the run state is idle, replace the container by the existing
   explicit sandbox create path, using the same workspace mount and
   permission mode. Do not use automatic health rebuild for this replacement.

An operator has not run this procedure. A container image label, including a
missing or different `source_digest`, leaves the loaded tool server version
unattested. This document does not perform a rebuild.
