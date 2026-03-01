# Agent Domain Model - Largest Bounded Context

The agent bounded context models the entire AI agent lifecycle: conversations, messages,
tasks, skills, sub-agents, HITL (human-in-the-loop), planning, and execution tracking.

## Subdirectory Map

| Subdir | Contains |
|--------|----------|
| `config/` | Agent configuration value objects |
| `conversation/` | Conversation entity and related types |
| `execution/` | Execution records, checkpoints, status tracking |
| `hitl/` | HITL request/response models, approval flows |
| `planning/` | Plan, WorkPlan, step definitions |
| `skill/` | Skill entity, trigger modes, composition |

## Key Top-Level Files

| File | Responsibility |
|------|---------------|
| `message.py` | Message entity (user/assistant/tool messages) |
| `task.py` | Task entity for agent task tracking |
| `subagent.py` | SubAgent entity definition |
| `subagent_run.py` | SubAgent execution run record |
| `subagent_result.py` | SubAgent execution result |
| `tenant_agent_config.py` | Per-tenant agent configuration |
| `tenant_skill_config.py` | Per-tenant skill configuration |
| `agent_execution.py` | Agent execution aggregate |
| `agent_execution_event.py` | Execution event records |
| `execution_status.py` | ExecutionStatus enum (state machine) |
| `agent_mode.py` | Agent operation mode enum |
| `hitl_request.py` | HITL request entity |
| `hitl_types.py` | HITL type enums (clarification/decision/env_var/permission) |
| `tool_composition.py` | Tool chain/composition definitions |
| `tool_execution_record.py` | Individual tool execution records |
| `tool_environment_variable.py` | Tool env var requirements |
| `workflow_pattern.py` | Learned workflow patterns |
| `prompt_template.py` | Prompt template entity |
| `thought_level.py` | Thought level enum for reasoning depth |
| `step_result.py` | Individual step results |
| `reflection_result.py` | Agent self-reflection results |
| `attachment.py` | File attachment value object |
| `skill_source.py` | Skill source enum (builtin/filesystem/custom) |
| `subagent_source.py` | SubAgent source enum |

## Patterns

- State machines: `execution_status.py` defines valid transitions
- HITL types: `clarification`, `decision`, `env_var`, `permission` — each requires different UI handling
- Skill trigger modes: `keyword`, `semantic`, `hybrid` — affects routing in L2
- All entities carry `project_id` for multi-tenant isolation
- SubAgent entities reference parent conversation via `conversation_id`

## Gotchas

- `execution/` subdir vs top-level `agent_execution.py` — the subdir has detailed execution tracking, top-level has the aggregate
- `hitl/` subdir vs `hitl_request.py` + `hitl_types.py` — subdir has flow logic, top-level has entities
- `skill/` subdir has skill runtime models, distinct from `skill_source.py` (enum) at top level
