# Automation

[backend/](backend/) owns scheduling commands, automation projections and webhook configuration. The live scheduler and the isolated `next_scheduled_run` preview construct the same APScheduler trigger in [triggers.py](triggers.py). The preview accepts a timezone-aware starting timestamp and a normalized schedule. It returns one eligible instant or null for an expired one-shot schedule. It never registers a job or sends an event.

[workflow/](workflow/) owns the asynchronous workflow engine, its contract and the task manager. The package worker dispatches `run_schedule_workflow` through this engine. It accepts up to sixteen schedule previews and returns their results in order. In the full service, [the runtime provider](backend/workflow_runtime.py) also accepts handlers registered by another business package. Knowledge owns the graph jobs and resolves the authorized graph scope for each job.

## Publish

From this directory build the worker, sign the package with the immutable image digest, and approve the resulting release for your project.

```sh
docker buildx build --push -t "$IMAGE:$VERSION" --metadata-file "$METADATA" .
DIGEST=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["containerimage.digest"])' "$METADATA")
STAGE=$(mktemp -d)
cp contributions.json "$STAGE/"
mkdir "$STAGE/ui"
cp ui/settings.json "$STAGE/ui/"
python3 -c 'import json,sys; print(json.dumps({**json.load(open("package.json")), "version": sys.argv[1]}))' "$VERSION" > "$STAGE/package.json"
python3 -c 'import json,sys; print(json.dumps({"schema":"memstack.mcp-oci-worker/1","image":sys.argv[1],"entrypoint":"/app/schedule-worker"}))' "$IMAGE@$DIGEST" > "$STAGE/worker.json"
uv run --with ../../../sdk/memstack-plugin-sdk memstack-plugin-pack "$STAGE/package.json" --key "$SIGNING_KEY" --out automation.mspkg
memstack packages --tenant "$TENANT" --project "$PROJECT" install --approve ui.slot --approve tools.execute automation.mspkg
```

From the repository root run the scheduler regressions under `src/tests/unit/infrastructure/scheduler`. Run `OCI_WORKER_DOCKER_TESTS=1 uv run pytest src/tests/integration/test_automation_schedule_package.py` to verify the signed worker through both full and minimal HTTP hosts.
