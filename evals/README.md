# MemStack Agent Evals

This folder is an independent evaluation project for MemStack agents. It lives in the
repository for versioning, but it must not import or depend on the application packages under
`src/`, `web/`, or `configuration/`.

The first evaluation framework is `mini-swe-agent`. The harness runs software-engineering cases in
temporary workspaces, captures trajectories, verifies results with shell commands, and emits JSONL
reports.

## Install

```bash
cd evals
uv sync --extra dev
```

## Dry Run

```bash
cd evals
uv run memstack-agent-evals run cases/smoke_toy_repo.yaml --runner mini --dry-run
```

## Isolation

Evaluation code must use only black-box boundaries:

- subprocess commands
- local git clones or worktrees
- HTTP/WebSocket calls to an already-running service

It must not import `src.*`, `web.*`, or `configuration.*`.
