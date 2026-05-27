---
name: drone
description: "Run tenant-configured Drone pipelines from ordinary chat using repository-scoped CI/CD. Use when the user asks to build, test, deploy, release, or inspect a Drone pipeline."
tools:
  - cicd_run_pipeline
---

# Drone CI/CD

Use the `cicd_run_pipeline` tool for Drone build, test, deploy, release, and pipeline-run requests.

## Required Inputs

- Always provide `repository` or `repo` as `<owner>/<repo>`.
- Do not pass `workspace_id`. Ordinary-chat CI/CD is repository-scoped and does not require a workspace.
- If the user has not provided a repository, infer it only from explicit current conversation or project evidence. If there is no explicit repository evidence, ask for the repository slug.

## Optional Inputs

- Use `branch` when the user names a branch or when explicit project evidence identifies one.
- Use `commit` only when the user provides a commit SHA.
- Use `target` for a named Drone target, environment, or deployment stage.
- Use `params` for pipeline variables requested by the user.
- Use `wait=true` for deploy requests where the user expects completion status.
- Use `reason` to summarize why the pipeline is being triggered.

## Configuration Model

Tenant plugin configuration stores Drone connection settings only:

- Drone server URL environment variable name.
- Drone token environment variable name.
- Poll interval seconds.

Do not rely on plugin-level default repository or default branch values. The repository must come from the tool call.

## Deploy Workflow

1. Identify the Drone repository in `<owner>/<repo>` format.
2. Use `cicd_run_pipeline` with `repository`, optional `branch`, optional `target`, and `wait=true` for deployment requests.
3. Report the returned external id, external URL, pipeline status, and stage statuses.
4. If the deployment exposes a health URL or application URL in the pipeline output, verify and report it.

## Local Drone Notes

- Local Docker deploys that mount the host Docker socket require the Drone repository to be trusted.
- For host Docker socket deploys, mount `/var/run/docker.sock` at the pipeline top level rather than relying on Docker-in-Docker service networking.
- For the local insecure registry in this dev stack, prefer `127.0.0.1:5001` in image names used by Docker push and pull. Avoid `host.docker.internal:5001` unless the Docker daemon is explicitly configured for that registry host.

## Boundary

The workspace pipeline harness and `workspace_pipeline_*` tables are for workspace-owned CI/CD. This skill uses ordinary-chat `cicd_run_pipeline`, which writes ordinary CI/CD run records and should not choose or require a workspace.
