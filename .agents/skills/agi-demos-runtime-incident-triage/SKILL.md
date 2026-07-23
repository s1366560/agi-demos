---
name: agi-demos-runtime-incident-triage
description: Evidence-led triage and scoped recovery for local MemStack development runtime incidents. Use when FastAPI, React/Vite Web, Ray, the agent actor, Docker infrastructure, Redis, Postgres, Neo4j, the sandbox, or the Electron desktop sidecar fails to start, crashes, consumes abnormal resources, or becomes unresponsive.
---

# Triage MemStack Runtime Incidents

## Keep the scope narrow

- Operate only on the local MemStack development runtime in this repository.
- Cover startup failures, crashes, abnormal CPU or memory use, hangs, and lost responsiveness.
- Exclude production incidents, broad architecture reviews, feature debugging without a runtime symptom, periodic monitoring, and generic performance tuning.
- Preserve the initial failure state until enough evidence exists to identify the owning substrate.
- Do not begin with `make restart`, a full Compose restart, a machine reboot, or another broad reset.
- Never run `make reset`, `make fresh`, `docker compose down -v`, `docker-clean`, or delete caches, containers, volumes, or data as a diagnostic shortcut.
- Never modify Postgres, Redis, or Neo4j data directly. Use health and connectivity checks only.
- Never dump environment variables, secret files, credentials, tokens, cookies, connection strings, or complete container inspection output. Redact secrets from quoted logs.

## Collect the inputs

Record or discover:

- the exact symptom and first observed time;
- the affected surface, URL, port, process, container, or desktop action;
- the expected result and the smallest known reproduction;
- the command used to launch the runtime;
- the last known good state and relevant code, dependency, migration, or configuration changes;
- any non-secret tenant, project, workspace, conversation, request, or trace identifier needed to scope evidence.

Ask the user only for missing information that blocks safe progress. Do not ask them to repeat facts available from the repository, current terminal, or bounded local logs.

## Follow the evidence ladder

Complete these stages in order. Do not edit code or restart a substrate before stages 1–4 establish a supported target.

### 1. Fix the incident scope

1. State one concise incident question, such as “Why does the API on port 8000 fail health checks after the current backend change?”
2. Set a bounded time window around the failure.
3. Record the launch path and whether it ran on the host, in Docker, or through the native desktop shell.
4. Capture the current worktree state with `git status --short` without changing it.
5. Name the smallest suspected component, but treat it as a hypothesis until evidence confirms it.

If the machine is at immediate risk from a runaway process, capture its PID, owner, command, and one resource sample first. Stop it only when it is proven in scope and stopping it is already authorized.

### 2. Gather read-only state, logs, and resources

Prefer bounded commands. Record `date -u +%Y-%m-%dT%H:%M:%SZ` immediately before and after each
observation, and give network or health probes an explicit bounded timeout. Read a Make target
before relying on it when its read-only behavior is not already known. Start with:

```bash
make status
lsof -nP -iTCP:8000 -sTCP:LISTEN
lsof -nP -iTCP:3000 -sTCP:LISTEN
curl --connect-timeout 3 --max-time 10 -fsS http://127.0.0.1:8000/health
# Only after confirming the source is already redacted:
tail -n 200 <confirmed-redacted-log>
docker compose ps
docker stats --no-stream <confirmed-container>
```

Use bounded probe arguments in the executable command, for example:

```bash
curl --connect-timeout 3 --max-time 10 -fsS http://127.0.0.1:8000/health
```

Use only the checks relevant to the scoped component:

- API or Web: inspect the port owner, PID file, process lineage, bounded host log, and health response.
- Ray or agent actor: first resolve the actual Compose service and container names from the active
  Compose project. Then inspect bounded logs for the confirmed Ray or actor containers, plus health,
  restart count, and short scoped resource samples.
- Postgres: use `docker compose exec -T postgres pg_isready -U postgres`; do not issue data-changing SQL.
- Redis: use `docker compose exec -T redis redis-cli ping`; do not enumerate keys or values without a separately justified need.
- Neo4j: inspect its Compose health status or run the configured non-mutating readiness check; do not mutate graph data.
- Sandbox: use `make sandbox-status` and bounded `docker logs --since ...`; do not rebuild or recreate it yet.
- Desktop: observe the terminal launched by `make -C agi-stack run-desktop`, Electron process boundaries, and the private sidecar lifecycle. Do not launch the sidecar directly and do not substitute the renderer-only Vite server.

For high-resource or intermittent incidents, collect at least three bounded samples for only the
confirmed in-scope processes or containers rather than relying on a single snapshot. Avoid
unbounded `-f` log followers and full `docker inspect` output. Prefer a source command or
repository filter that redacts credential-shaped fields before output reaches the agent transcript.
If no pre-output redaction path exists and the source may contain secrets, do not run the raw dump;
request a user-supplied redacted excerpt or use structured health, status, and counter fields
instead. Quote only the minimum decisive lines and never relay a connection string or token.

### 3. Attribute the owning substrate

Distinguish among these boundaries before choosing a recovery:

| Boundary | Confirm with |
|---|---|
| Host application | Port owner, PID lineage, host log, health endpoint, launch terminal |
| Container/runtime dependency | Compose service state, health, restart/OOM state, bounded service log, resource samples |
| Repository code/configuration | Reproduction under the canonical launch command, stack trace, relevant diff, dependency or migration state |

Write a primary hypothesis and at least one competing hypothesis. For each, cite supporting and contradicting observations. Continue read-only checks until one next action clearly discriminates between them.

Do not attribute a failure to repository code merely because the worktree is dirty. Do not attribute it to Docker merely because a service is containerized.

### 4. Map code before any symbol edit

If evidence points to repository code:

1. Use GitNexus `query` to locate the relevant execution flow.
2. Use GitNexus `context` when the failing symbol needs caller, callee, or process context.
3. Run GitNexus upstream `impact` for every function, class, or method before editing it.
4. Report direct callers, affected processes, and the returned risk level.
5. Stop and warn the user before editing when impact is HIGH or CRITICAL.

Do not edit a symbol when GitNexus impact has not run. Do not make speculative cleanup changes while
repairing the incident. If evidence identifies only an operational state problem, mark this stage
`not applicable` with the supporting observation and recover that state without running irrelevant
code-impact analysis.

### 5. Reproduce and test the smallest failure

Before the fix, preserve a deterministic failing command, test, or bounded reproduction whenever possible. Then:

1. Add or adjust the narrowest regression test alongside a code fix.
2. Run the focused test first.
3. Run the nearest subsystem test and applicable lint or type check.
4. Record commands, exit status, and concise results.

Do not claim success from a passing unit test alone when the incident occurred in a live runtime.

### 6. Reload the correct substrate

Reload only the component that owns the changed state:

- Host API: restart only the scoped API process and use `make dev-backend` when a foreground canonical launch is appropriate.
- Web: rely on Vite HMR when it applied the change; otherwise use `make dev-web-stop` and `make dev-web`.
- Ray: use `make ray-up-dev` for the volume-mounted development runtime and `make ray-reload` when Ray services need a scoped reload. Rebuild only when evidence shows the active image cannot consume the change.
- Agent actor: resolve the active Compose project and exact service name before a scoped restart;
  use `make agent-actor-up` when the canonical actor service is stopped. For a running or
  crash-looping actor, restart only that resolved service with the same active Compose files and
  project options used to launch it:
  `docker compose <active-options> restart <resolved-service>`. Do not treat a container display
  name as a Compose service name and do not fall back to a raw container restart.
- Docker dependency: restart only the unhealthy named service; preserve volumes.
- Sandbox: use `make sandbox-restart` only after sandbox evidence identifies it as the owner.
- Desktop: launch and validate only with `make -C agi-stack run-desktop`; let Electron own the Rust sidecar through its authenticated control pipe.

Re-check status immediately after reload. If the selected substrate did not load the change, stop and re-evaluate the boundary rather than widening the restart.

### 7. Prove recovery and sample stability

Repeat the original reproduction against the live runtime. Verify:

- the intended health, endpoint, UI, agent action, sandbox action, or desktop action succeeds;
- the relevant process or container remains running without a new restart or OOM event;
- bounded logs contain no recurrence of the scoped error;
- at least three resource samples cover a window longer than the longest observed pre-fix recurrence
  interval and show no continuing runaway trend;
- the same non-secret request, conversation, or trace scope is used when the incident depends on runtime context.

Choose the sample window with an available agent/subagent structured tool-call using the observed
failure interval, runtime cost, and affected surface. Require the call result and audit record to
include `agent_id`, `tool_name`, `input`, `output`, `rationale`, and `latency_ms`, plus the proposed
window and semantic `resolved | mitigated | unresolved | blocked` verdict. Store redacted JSONL in
a repository-external, mode-`0700` temporary evidence directory; retain compact references and
summaries, never secrets, personal data, or raw log bodies. Measure elapsed wall time when the tool
does not return latency, and never add this evidence directory to the worktree. If no structured
judgment mechanism is available, do not automate the semantic verdict; report the deterministic
observations and leave status `unresolved` or `blocked` as applicable.

The deterministic minimum is a window longer than the longest observed pre-fix recurrence interval
with at least three samples. If no complete recurrence interval is known and deterministic
reproduction is unavailable, sample for at least 15 minutes with at least three observations; that
evidence can support only `mitigated`, never `resolved`. A `resolved` verdict requires either a
known recurrence interval that the sample exceeds or a deterministic live reproduction that passes
after recovery. Do not replace live proof with code inspection.

## Stop for permission

An exact, reversible reload of the conclusively identified local MemStack service is a normal step
when the user asked for a fix. It does not require a second confirmation unless the environment
requires approval. Pause and request authorization before:

- killing a process that is not conclusively scoped to this repository, or using a raw signal when a
  canonical scoped stop/restart path is available;
- using elevated host access, controlling a GUI, or leaving the sandbox;
- installing dependencies or accessing the network;
- opening secret stores or requesting credentials;
- deleting or recreating containers, caches, volumes, databases, or user data;
- applying a migration, issuing a data-changing database command, or changing external systems;
- expanding from a local development incident into production or shared infrastructure;
- proceeding with a HIGH or CRITICAL GitNexus blast radius.

Do not work around a denied permission. Report the exact blocked check and the safest next action.

## Report the result

Return a concise incident record containing:

1. scope, time window, reproduction, and affected substrate;
2. timestamped, redacted evidence and the commands or sources that produced it;
3. primary and competing hypotheses with the decisive observation;
4. GitNexus query, context, and impact results when code changed;
5. code changes or operational recovery performed;
6. tests, reload command, live proof, and stability sample;
7. final status: `resolved`, `mitigated`, `unresolved`, or `blocked`;
8. the smallest next discriminating action for any non-resolved status.

Mark the incident `resolved` only when the original live reproduction passes after the correct substrate reload and the bounded stability sample shows no recurrence. Mark it `mitigated` when service is restored but root cause or regression proof remains incomplete. Mark it `blocked` only at a defined permission or access stop. Otherwise mark it `unresolved` and preserve the evidence gathered.
