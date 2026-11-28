# Automation

Both clients load the [signed page entries](ui/signed/build.mjs). The original Cron form, store, jobs API, event, webhook and playbook clients live under [ui/web](ui/web).

[backend/](backend/) owns scheduling commands, automation projections and webhook configuration. The live scheduler and the isolated `next_scheduled_run` preview construct the same APScheduler trigger in [triggers.py](triggers.py). The preview accepts a timezone-aware starting timestamp and a normalized schedule. It returns one eligible instant or null for an expired one-shot schedule. It never registers a job or sends an event.

[workflow/](workflow/) owns the asynchronous workflow engine, its contract and the task manager. The package worker dispatches `run_schedule_workflow` through this engine. It accepts up to sixteen schedule previews and returns their results in order. In the full service, [the runtime provider](backend/workflow_runtime.py) also accepts handlers registered by another business package. Knowledge owns the graph jobs and resolves the authorized graph scope for each job.

## Publish

From the repository root, build the package pages and sign the release using the published worker image's immutable digest. Set `IMAGE` to the full image reference and `OUT` to a new output directory.

```sh
corepack pnpm --dir plugins/business/automation/ui/signed install --frozen-lockfile
node plugins/business/automation/ui/signed/build.mjs
PYTHONPATH=.:sdk/memstack-plugin-sdk/src uv run python -m scripts.build_standard_packages \
  --package automation --automation-image "$IMAGE" --key "$SIGNING_KEY" --out "$OUT"
```

From the repository root run the scheduler regressions under `src/tests/unit/infrastructure/scheduler`. Run `OCI_WORKER_DOCKER_TESTS=1 uv run pytest src/tests/integration/test_automation_schedule_package.py` to verify the signed worker through both full and minimal HTTP hosts.

The shared signed Playbooks page renders the original Web library in both clients using the `list-playbooks` and `list-verdicts` commands. The application runtime reads the authenticated project membership and the generation-bound playbook repository. Schedule previews run in the package worker independently of that runtime.
