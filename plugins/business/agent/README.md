# Agent

The signed `memstack-agent` release provides Skill validation, a format-review SubAgent, and conversation execution statistics. The same release drives each ReAct turn. These operations share one installation, worker image, version and rollback. The ReAct implementation lives in [engine/react/](engine/react/) and [engine/processor/](engine/processor/). The full chat and Ray entry points import this package.

- [react_loop.py](react_loop.py) selects the next instruction from the completed phase, step count and structured result. The signed OCI worker makes this decision for a project that grants `agent.loop.drive`. [turn.py](turn.py) interprets it using the run’s existing model, goal evaluator, tools, cancellation and budget. No conversation content is passed to the driver. Each run pins the package identity, version, digest and authorization epoch; a running turn can finish under its original version after an upgrade. A project run without a signed loop grant fails before its model step. Unscoped calls to the Python library use the packaged control function directly.
- Start at [skill_validation/validator.py](skill_validation/validator.py) to change how a supplied document is checked. [skill_validation/cli.py](skill_validation/cli.py) exposes the local and project CLI.
- Start at [execution_statistics/aggregate.py](execution_statistics/aggregate.py) for counts, distributions and time buckets. [backend/conversation_execution_statistics.py](backend/conversation_execution_statistics.py) reads authorized project history and maps private tool names to per-request integers.
- [contributions.json](contributions.json) defines operation schemas and the reviewer's allowed tool. [worker.py](worker.py) serves the signed operations in an isolated container.
- From the repository root, run `uv run pytest plugins/business/agent/tests`. With a Docker daemon and the publisher SDK installed, set `OCI_WORKER_DOCKER_TESTS=1` to run `src/tests/integration/test_project_execution_statistics.py` and `src/tests/integration/test_skill_validation_package.py` against disposable workers.

The signed chat page loads the [shared Web and desktop workbench](ui/signed/WebChatPage.tsx) from the same release. It uses scoped commands for conversations, P5 history, cloud turns and cancellation. The full API authenticates each call and restricts history and run IDs to the selected user, tenant and project. Web replays local conversations read-only. On desktop a new conversation defaults to this device. The signed page uses the local_chat device tool to send and stop a turn with the same idempotency key, then reloads P5 history. The device runtime checks the approved Agent release and supplies the workspace selected in device settings. A standalone kernel can reach the full API through `PACKAGE_APPLICATION_RUNTIME_URL` when both deployments share an identity authority, the same project, and the same active signed package digest. An unconfigured kernel reports unavailable application commands.

Run `uv run pytest src/tests/integration/test_package_chat_runtime.py` to exercise signed command admission, WebSocket events, cancellation and persisted replay using a deterministic model-stream fixture.

The full Web client keeps conversation state and history actions in [ui/web/stores/agent](ui/web/stores/agent/). The desktop conversation timeline, search and export models live in [ui/desktop/chat](ui/desktop/chat/). Transport and credentials belong to each client runtime.

## Tenant dashboard

A tenant administrator can approve the dashboard independently in the tenant marketplace. Open **Multi-agent dashboard** or the original Web bookmark `/tenant/:tenantId/agents`. Members see their own conversations, and tenant administrators can inspect runs across the tenant. Selecting a run opens its original trace chain. The tenant configuration editor checks the current revision on save. V2 Profiles own lifecycle hook mutations.

The tenant installation grants `ui.slot`, `tools.execute`, `app.agent.dashboard.read`, `app.agent.dashboard.trace` and `app.agent.dashboard.configure`. Listing or creating sessions without a selected project also needs `app.agent.list`, `app.agent.create` and `app.agent.history` on that tenant installation. A project installation continues to use its existing chat and device permissions. The signed project and tenant pages use the same release. Agent commands run in a separate guest process; they are not in-process `host_operation` handlers.

## Publish and install

From this directory, build an OCI image and sign the immutable digest with an Ed25519 publisher key. The SDK and the wheel can also be installed in a separate publisher environment.

```sh
docker buildx build --push -t "$IMAGE:$VERSION" --metadata-file "$METADATA" .
DIGEST=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["containerimage.digest"])' "$METADATA")
uv run --with . --with ../../../sdk/memstack-plugin-sdk memstack-agent-release \
  --image "$IMAGE@$DIGEST" --version "$VERSION" --key "$SIGNING_KEY" --out agent.mspkg
memstack packages --tenant "$TENANT" --project "$PROJECT" install \
  --approve ui.slot --approve tools.execute --approve subagents.register --approve agent.loop.drive \
  --approve app.agent.list --approve app.agent.create --approve app.agent.history \
  --approve app.agent.turn --approve app.agent.cancel --approve app.agent.rename \
  --approve app.agent.interactions --approve app.agent.respond \
  --approve app.agent.attachments --approve app.agent.attachments.turn \
  --approve app.agent.activity.read --approve app.agent.activity.receipts \
  --approve app.agent.review.latest --approve app.agent.review.details \
  --approve device.local-chat agent.mspkg
```

The project administrator must trust the publisher and permit the image registry. Select `memstack-agent` as the conversation's `execution_stats_package` to use the signed statistics. Project-mode `memstack-skill-validate` addresses the same installation.
