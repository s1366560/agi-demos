---
name: agi-demos-commit-all
description: Inspect, organize, validate, and commit the complete current agi-demos dirty worktree, with optional explicit push. Use when the user says commit all, 提交所有变更, 按逻辑提交所有变更, commit and push all, or an equivalent full-tree Git delivery request in this repository.
---

# Commit All agi-demos Changes

Treat “all” as authorization for the complete current dirty tree, not only changes made by the
active agent. Preserve every change and do not ask the user to narrow an already explicit
full-tree request.

Do not use this skill for a focused commit, pull-request review, history rewrite, revert, or
destructive cleanup.

## Select the delivery mode

- Use `full-tree` when the request says commit all or 提交所有变更. Include every safe,
  non-ignored tracked and untracked change. Use one commit only when the tree represents one
  coherent outcome; otherwise use agent judgment to keep independently reversible outcomes
  separate.
- Use `logical-local` when the request says 按逻辑提交所有变更 or explicitly asks for grouped
  commits. Split the full tree into dependency-safe, buildable thematic commits and stop locally.
- Add `push` only when the user explicitly says push, 推送, publish, or requests a remote
  delivery. Do not open a pull request unless separately requested.

Logical grouping is subjective. Use an agent or subagent structured tool-call to propose groups
with a natural-language rationale. Do not classify changes through filename regexes, keyword
tables, or fixed semantic buckets.

Use the same structured judgment path for whether concurrent work fits the user's authority,
whether generated metadata belongs to the current `HEAD`, and whether a hook failure is substantive
or unrelated. Create a repository-external, mode-`0700` task evidence directory and append one
JSONL record per judgment with `agent_id`, `tool_name`, `input`, `output`, `rationale`, and
`latency_ms`; measure elapsed wall time around the call when the tool does not return latency.
Before writing, redact secrets, tokens, personal data, scanner matches, and complete source or diff
bodies; retain compact references and summaries. Never include this evidence directory in the
worktree or commit scope. If no structured judgment mechanism is available, stop at the ambiguous
boundary rather than applying a deterministic semantic rule.

## Establish the full-tree snapshot

Read the repository-root `AGENTS.md` and keep its security, Conventional Commit, Lore,
GitNexus, and dirty-worktree rules active.

Capture the baseline without modifying it:

```bash
git status --short --branch
git diff --stat
git diff --cached --stat
git ls-files --others --exclude-standard
git log -5 --oneline --decorate
```

Inspect the actual diffs, including pre-existing and staged changes. Record:

- tracked, staged, unstaged, and non-ignored untracked paths;
- deletions, renames, generated artifacts, submodules, and large binary files;
- the current branch, upstream, ahead/behind state, and recent commits;
- changes that another running task may still be modifying.

Exclude dependency and build caches such as `node_modules`, `.pnpm-store`, `dist`, and `target`
even when a local ignore rule is missing; this explicit exclusion overrides the general
non-ignored-untracked rule. Do not force-add ignored files.

Before staging, resolve the repository-configured secret scanner and the named remote host's
per-object size limit. Scan the complete candidate file content and binary metadata without
printing matched values. If no configured scanner exists, request approval to use an official
scanner from a mode-`0700` temporary directory. Pin its exact version, verify its published checksum
against the official release source, record both in the evidence packet, and do not modify the
repository or global toolchain. If network access or that approval is unavailable, stop and report
the missing safety check; do not substitute visual staged-diff review.

Identify the named remote host even for a local-only commit, verify its current authoritative
per-object limit, and size-check every object newly introduced by the commit against that limit
because a later push would carry the same object. If the host or limit cannot be resolved, stop
before committing. Report a sensitive or oversized candidate without committing it.

Never reset, clean, discard, rewrite, or overwrite user changes.

## Plan dependency-safe commits

For `logical-local`, or when `full-tree` contains multiple independent outcomes:

1. Ask an agent/subagent tool-call to map files and hunks to cohesive outcomes.
2. Check cross-file imports, schemas, migrations, generated counterparts, tests, docs, and build
   contracts before finalizing boundaries.
3. Order commits so each intermediate state is understandable and, where practical, buildable.
4. Keep behavior with its tests and required schema/config changes.
5. Keep generated metadata with the source change that generated it, unless the repository
   intentionally tracks it as a separate maintenance commit.
6. Present the compact group plan before staging, then proceed without asking for confirmation
   unless a destructive, sensitive, or materially out-of-scope action is required.

Do not split a file by hunk unless the hunks are truly independent and the index can be staged
safely. Never use a worktree rewrite to manufacture clean boundaries.

If the initial index already spans multiple logical groups, first record the staged patch. Use
`git restore --staged -- <reviewed-paths>` only for explicit paths that must move to a later group;
this changes the index without discarding worktree content. Re-read both staged and unstaged diffs
after each index change. Never use `git reset` to reorganize the index.

## Stage and validate each commit

For every group:

1. Stage explicit paths or reviewed hunks. Use `git add -A` only when the current group is the
   entire remaining safe tree.
2. Review `git diff --cached --stat`, `git diff --cached`, and
   `git diff --cached --check`.
3. Run GitNexus `detect_changes` with staged scope through the MCP tool before committing. Reconcile
   affected symbols and execution flows with the planned group. Warn and stop on unexpected HIGH
   or CRITICAL scope.
4. Run the smallest relevant tests, lint, type checks, or builds not already proven for that
   group. Do not claim unrelated full-suite coverage.
5. Commit with a valid repository subject:

   ```text
   <feat|fix|refactor|docs|test|chore>(optional-scope): concise summary
   ```

6. When a body is useful, follow the current Lore protocol in `AGENTS.md`; do not invent trailer
   names that are not defined there.
7. Let all hooks run. Apply deterministic formatting or generated-file updates only when they stay
   inside the reviewed group. A substantive or unrelated hook failure requires structured scope
   judgment and re-planning. Stop and obtain additional authority before fixing it when the repair
   would introduce a new unrelated source change. Never use `--no-verify`.
8. If a hook or formatter changes files belonging to the same commit, review and restage them,
   rerun staged checks, and amend with `git commit --amend --no-edit`.
9. Re-run `git status --short` and confirm the remaining tree matches the remaining group plan.

If another task commits or changes the tree during the workflow, stop staging, re-read status and
recent history, and resolve the new state. Do not create an empty or duplicate commit. Include
newly arrived changes under an explicit “all” request only after they are no longer being written,
have been fully reviewed, and a structured judgment confirms they fit the same authority.
Re-snapshot and re-plan them first. Leave mid-write or materially different changes untouched and
report them as concurrent rather than capturing another task's incomplete state.

## Refresh GitNexus without creating metadata churn

Do not assume `.gitnexus/run.cjs` is pinned: inspect its resolution path because the generated
runner may select a global binary or `gitnexus@latest`. Resolve the exact GitNexus version from the
active repository lockfile, then verify the executable's `--version` matches it. Use a lock-backed
local executable only after that check. Do not let `npx`, `pnpm dlx`, the generated runner, or a
global binary download or run an unverified version. When the index is stale after the commits, run
the verified local executable:

```bash
./node_modules/.bin/gitnexus analyze --skip-agents-md
```

If the lock-backed executable is missing or its version differs, request approval before
materializing the exact locked version. If compatibility cannot be established, report the blocked
refresh instead of falling back to another installed version.

Inspect the tree again because analysis can still update tracked metadata. Default to reporting
post-refresh drift without committing it. Amend only when the metadata is demonstrably required by
a baseline source change and a structured scope judgment confirms it belongs to the current
`HEAD`. Do not create a maintenance commit for generator output that was absent from the baseline
merely because refresh produced it. Run staged `detect_changes`, checks, and hooks again for any
approved metadata. Allow at most two refresh/amend cycles; if metadata still changes, stop and
report the unstable generator. Do not use nonexistent `detect-changes` CLI variants as a substitute
for the MCP `detect_changes` tool.

## Push only when explicit

If push is requested:

1. Keep the current non-default branch when appropriate. When a new branch is required, use the
   repository `codex/` prefix unless the user names another branch.
2. Re-check upstream divergence before pushing. Do not force-push unless the user explicitly
   authorizes that history rewrite.
3. Push the current branch and verify the remote ref equals local `HEAD`.
4. If SSH transport fails, retry with a repository-scoped HTTPS remote URL without exposing or
   persisting credentials. Do not change global Git configuration.
5. Do not create a PR as an implicit side effect.

## Finish only on verified state

For a local-only request, finish when:

- every safe path from the full-tree scope belongs to a verified commit;
- excluded paths are explicitly reported with the reason;
- the remaining worktree is clean, or contains only explicitly reported cache/sensitive/oversized
  exclusions and clearly identified concurrent/out-of-authority changes;
- GitNexus scope and repository status are stable;
- commit subjects and hooks passed.

For a push request, additionally require the remote branch to match local `HEAD`.

Report the commit list in logical order, validation per commit, exclusions, final branch/upstream
state, and whether push occurred. Never report a clean tree, successful hook, or remote delivery
without checking it directly.
