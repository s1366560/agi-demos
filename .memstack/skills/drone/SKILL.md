---
name: drone
description: Configure, review, and operate Drone CI/CD for MemStack software workspaces. Use when Codex needs to create or update .drone.yml, configure workspace metadata.delivery_cicd.provider=drone, set Drone API/server/runner environment variables, start or verify Drone Docker services, trigger or inspect Drone pipelines, or diagnose Drone CI/CD configuration and execution failures.
---

# Drone CI/CD

Use this skill to make Drone CI/CD work end-to-end for a programming workspace without leaking secrets or breaking the existing sandbox-native delivery path.

## Workflow

1. Identify the scope:
   - Workspace metadata only, `.drone.yml` only, infrastructure only, or full end-to-end.
   - Current code root and repository slug.
   - Whether the workspace already has an explicit non-Drone provider; preserve it unless the user asks to migrate.

2. Load repo-specific contract details from `references/memstack-drone.md` before editing workspace metadata, backend defaults, frontend workspace forms, or tests.

3. Load pipeline examples from `references/pipeline-patterns.md` before writing or reviewing `.drone.yml`, Drone secrets, runner requirements, or pipeline diagnostics.

4. Configure secrets by reference only:
   - Store token names and env-var names in workspace metadata.
   - Never place `DRONE_TOKEN`, OAuth secrets, RPC secrets, API keys, or generated tokens directly in metadata, YAML, test fixtures, logs, or final responses.

5. Verify in layers:
   - Metadata normalization and contract parsing tests.
   - `.drone.yml` syntax and project commands.
   - Docker Compose Drone profile parsing.
   - Local Drone service startup only when needed for the task.
   - Drone build status, logs, and evidence refs when a pipeline run is part of the request.

## Output Expectations

Report the changed workspace contract, pipeline file path, verification commands, and any missing external setup such as GitHub OAuth app credentials, repository activation, or Drone secrets. Keep unresolved secret values redacted and identify them by env-var or secret name only.
