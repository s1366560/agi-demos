---
name: docker-compose
description: "Run Docker Compose operations through a configured and sandbox-safe Docker daemon environment. Use when the user asks to inspect, start, stop, build, rebuild, pull, push, exec, log, or configure services with Docker Compose."
tools:
  - docker_compose
---

# Docker Compose

Use the `docker_compose` tool for Docker Compose operations.

## Command Shape

- Put the full subcommand after `docker compose` in `compose_args`.
- Use argv-style arguments, not shell strings. For example, use `["up", "-d", "--build"]`.
- Use `workdir` for the compose project directory.
- Use `client_workdir` when the plugin/API process reads compose files from a different path
  than the agent or sandbox sees in `workdir`.
- Use `compose_files` for explicit compose files instead of embedding `-f` in `compose_args` when possible.
- Use `project_name` and `profiles` when the user needs a specific compose project or profile set.

## Runtime Environment

- Prefer `docker_host="tcp://..."`, `docker_host="ssh://..."`, or a named `docker_context`
  for sandbox-local or remote Docker daemons.
- Do not use a mounted Unix Docker socket from inside a sandbox container by default.
- Only set `allow_host_socket_from_sandbox=true` when the user explicitly wants host-daemon behavior and accepts host DNS/path semantics.
- When the Docker daemon runs on a different machine from the sandbox/API process, pass
  `daemon_workdir` or `path_mappings` so bind mounts use paths valid on the Docker daemon host.
- For cross-machine setups, treat paths as three separate namespaces:
  `workdir` is the agent/sandbox path, `client_workdir` is where this plugin reads compose
  files, and `daemon_workdir` is where the remote Docker daemon resolves bind mounts.
- Pass temporary environment variables in `env`; persistent defaults are configured through the plugin environment variables.

## Common Calls

- Inspect services: `compose_args=["ps"]`
- Validate config: `compose_args=["config"]`
- Start services: `compose_args=["up", "-d"]`
- Rebuild and start: `compose_args=["up", "-d", "--build"]`
- Stop services: `compose_args=["down"]`
- Logs: `compose_args=["logs", "--tail", "200"]`
- Execute command: `compose_args=["exec", "service", "command"]`

## Boundary

This plugin is the safe path for compose operations from agent turns. Avoid running raw terminal
`docker compose` commands when daemon selection matters, especially inside sandbox containers.
