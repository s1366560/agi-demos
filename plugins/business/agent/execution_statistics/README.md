# Conversation execution statistics

The package owns the counts, average duration, status and tool distributions, and timeline in the conversation execution statistics response. The host reads the authorized SQL history and maps labels to per-request integers. The worker receives up to 1,000 four-integer rows containing a status slot, optional tool slot, start minute and duration in microseconds. Only the host can resolve the slots to tool names and the conversation's original statuses.

The full host uses the package's bundled aggregation for sessions without a selection and preserves their original terminal-count conventions. Signed releases recognize the stored lowercase `completed` and `failed` enums as well as their uppercase spellings. The original endpoint continues to return chart labels in the timestamp's source clock.

## Publish and use a release

Build and sign the [Agent package](../README.md). Its worker exports both execution statistics and Skill validation.

The API needs the publisher's public key in `PLUGIN_MARKETPLACE_TRUSTED_KEY_FILES`, an authorized worker registry in `PLUGIN_WORKER_ALLOWED_REGISTRIES`, and its configured OCI supervisor. A project administrator installs the archive, grants `tools.execute`, `agent.loop.drive` and `subagents.register` and enables the release. Create a conversation in that project with `agent_config.execution_stats_package` set to `memstack-agent`.

Read `GET /api/v1/agent/conversations/{conversation_id}/execution/stats?project_id={project_id}` as the conversation owner. Reading the signed projection also requires project package execution permission. Disabling the selected release makes the projection unavailable. Upgrade and rollback take effect on subsequent reads. Core membership, conversation ownership, execution writes and workspace state continue through their existing authorities.
