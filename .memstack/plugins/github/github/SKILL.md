---
name: github
description: "Use GitHub repositories, issues, pull requests, commits, search, and files through the configured GitHub plugin."
tools:
  - github
---

# GitHub

Use the `github` tool for GitHub repository, issue, pull request, commit, search, and file requests.

## Repository Inputs

- Prefer explicit `owner` and `repo`.
- If tenant plugin configuration provides a default owner and repository, the tool wrapper can fill them.
- If no repository is explicit or configured, ask for `<owner>/<repo>` before repository-scoped operations.

## Common Operations

- Repository metadata: `operation="get_repo"`.
- Issues: `list_issues`, `get_issue`, `create_issue`.
- Pull requests: `list_pull_requests`, `get_pull_request`.
- Comments: `create_issue_comment`.
- Search: `search_repositories` with `query`.
- Files: `get_file` with `path` and optional `ref`.
- Commits: `list_commits` with optional `ref`.

## Write Safety

Mutating operations require `confirm_write=true` and a configured token environment variable.
Use writes only when the user clearly asked to create or comment on a GitHub resource.

## Configuration

The plugin reads GitHub credentials from an environment variable, defaulting to `GITHUB_TOKEN`.
For GitHub Enterprise, configure `api_base_url`.
