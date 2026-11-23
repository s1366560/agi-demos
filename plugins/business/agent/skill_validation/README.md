# Skill validation

This package owns the AgentSkills Markdown parser, validator and `memstack-skill-validate` command.
The local CLI accepts a skill directory, supports `--all` for a collection, and supports
`--strict` to treat warnings as errors. Install the wheel and run
`memstack-skill-validate --strict path/to/skill` to validate files locally.

The signed cloud tool `validate_skill` accepts the text of a single `SKILL.md` document and an
optional `strict` flag. A response contains `is_valid`, `errors` and `warnings` as well as their
counts. Its worker reads the supplied text in memory and needs only the `tools.execute` grant.

For a signed project release, install the CLI with its `cloud` extra, authenticate with
`memstack login`, then run `memstack-skill-validate --tenant "$TENANT" --project "$PROJECT" path/to/skill`.
This sends the selected Markdown text to the configured MemStack API, pins the active release for
the entire command, and exits with status 1 when validation finds errors.

## Publish a cloud release

Build and sign the [Agent package](../README.md).

The deployment's worker supervisor must have access to the OCI daemon. Include the registry origin
in `PLUGIN_WORKER_ALLOWED_REGISTRIES` and the publisher's Ed25519 public key in
`PLUGIN_MARKETPLACE_TRUSTED_KEY_FILES`. A project administrator installs the archive and enables
the release through the signed project package API. The worker runs without a network connection
or a project filesystem mount. Upgrade and rollback use the same installation record.

An authorized caller can invoke `validate_skill` at
`POST /api/v1/platform-plugins/v2/optional-business/memstack-agent/invoke` with
the tenant and project IDs, `tool_name` set to `validate_skill` and a payload such as
`{"content":"---\nname: review\ndescription: Check a change\n---\n# Review","strict":true}`.
Project Agent runs can delegate a supplied document to the signed Skill format reviewer.
Approve `subagents.register`, `agent.loop.drive` and `tools.execute` at installation. The reviewer inherits
the parent model and can call `validate_skill` only when that tool is visible to its parent.
It receives the task and the ordinary delegated conversation excerpt. The publisher owns
its prompt, display name, description and allowed package tools in `contributions.json`.
