# Prompts Module

Assembles the final system prompt sent to the LLM. Multi-layer architecture:
loader (file I/O) -> persona (structured fields) -> manager (assembly + injection).

## Key Files

| File | Purpose |
|------|---------|
| `manager.py` | `SystemPromptManager` — builds complete system prompt. Resolves model provider, injects tools/skills/memory/persona. 837 lines, central orchestration point. |
| `persona.py` | `AgentPersona`, `PersonaField`, `PersonaSource` — first-class persona types with source tracking, truncation metadata, diagnostics. Frozen dataclasses. |
| `loader.py` | `PromptLoader` — file loader with dict cache and `${VAR}` template substitution. Sync + async variants. |
| `tool_summaries.py` | `TOOL_SUMMARIES` dict + `TOOL_ORDER` list — curated one-line overrides for tool descriptions and preferred presentation order in prompt. |

## Subdirectories

| Dir | Contents |
|-----|----------|
| `system/` | Base system prompt templates per provider: `anthropic.txt`, `gemini.txt`, `qwen.txt`, `default.txt`. Each has a `_behavioral.txt` companion (overrideable persona/style section). |
| `workspace/` | Default persona templates: `SOUL.md`, `IDENTITY.md`, `AGENTS.md`, `HEARTBEAT.md`, `TOOLS.md`, `USER.md`. Fallback when project/tenant overrides absent. |
| `reminders/` | Mode-specific reminder injections: `build_mode.txt`, `plan_mode.txt`, `max_steps.txt`. |
| `sections/` | Reusable prompt sections: `workspace.txt`. |

## 3-Tier Persona Override

Resolution priority: **Project-level** > **Tenant-level** > **System default (workspace/ templates)**.
- Project files: `{sandbox_cwd}/.memstack/workspace/{SOUL,IDENTITY,...}.md`
- Tenant files: `{tenant_workspace_dir}/{SOUL,IDENTITY,...}.md`
- Default: this module's `workspace/` dir
- `PersonaSource` enum tracks origin: WORKSPACE, TENANT, TEMPLATE, CONFIG, NONE

## Assembly Flow (SystemPromptManager.build_prompt)

1. Resolve `ModelProvider` from LLM model name
2. Load core system prompt (`system/{provider}.txt`)
3. Load behavioral prompt (`system/{provider}_behavioral.txt`) — overrideable via persona
4. Build tool definitions section with `TOOL_SUMMARIES` overrides + `TOOL_ORDER` sorting
5. Inject skills, subagents, matched_skill context
6. Load persona fields (SOUL, IDENTITY, USER, AGENTS, TOOLS, HEARTBEAT) via 3-tier resolution
7. Inject memory context (sanitized against prompt injection)
8. Append mode-specific reminders (build/plan)
9. Return assembled prompt + `PromptReport` diagnostics

## Gotchas

- `memory_context` is sanitized via `prompt_safety.looks_like_prompt_injection()` before injection
- Persona fields are truncated to configurable char limits; `PersonaField.is_truncated` tracks this
- `PromptLoader` caches by full file path — stale cache possible if files change at runtime
- `_behavioral.txt` files are the overrideable "soul" portion; core `.txt` files are always included
- `workspace/AGENTS.md` is a TEMPLATE for projects, not this module's knowledge base
