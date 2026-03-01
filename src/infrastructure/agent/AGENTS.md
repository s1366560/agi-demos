# Agent Infrastructure -- Directory Map

Self-developed ReAct agent system. 30+ subdirectories implementing L1 Tool -> L2 Skill -> L3 SubAgent -> L4 Agent.

## Top-Level Files

- `__init__.py` -- exports `ReActAgent` and `AgentTool`
- `config.py` -- `AgentConfig` dataclass: flat config with backward-compat aliases. `ExecutionMode` enum (NORMAL/PLAN/EXPLORE/BUILD).
- `errors.py` -- `AgentError` hierarchy with `ErrorSeverity`, `ErrorCategory`, `ErrorContext`. All agent exceptions inherit from `AgentError`.
- `sandbox_resource_provider.py` -- provides sandbox resources (terminal, desktop) to tools at runtime

## Tier 1 Subdirectories (have own AGENTS.md)

- `core/` -- ReAct loop, LLM streaming, tool converter, subagent router/runner. See child AGENTS.md.
- `processor/` -- SessionProcessor: tool execution, event emission, artifact handling. See child AGENTS.md.
- `tools/` -- 40+ L1 tool implementations (todo, terminal, MCP, skills, web, env). See child AGENTS.md.
- `subagent/` -- L3 SubAgent: parallel scheduler, filesystem loader, markdown parser, run registry. See child AGENTS.md.
- `prompts/` -- System prompt assembly: persona, sections, reminders, workspace context. See child AGENTS.md.

## Tier 2 Subdirectories

### actor/
Ray Actor execution runtime. `execution.py` runs the main event loop: creates ProjectReActAgent, streams events, publishes to Redis Stream (`agent:events:{conversation_id}`). `actor_manager.py` manages actor lifecycle. `project_agent_actor.py` is the Ray Actor class. `state/` subdirectory handles running-state TTL and HITL snapshot persistence.

### events/
Domain event -> SSE dict conversion. `converter.py` has `EventConverter` class that transforms `AgentDomainEvent` subclasses to frontend-compatible dicts. `event_mapper.py` maps event types for routing.

### plugins/
Plugin runtime system. `manager.py` orchestrates plugin lifecycle. `discovery.py` finds entrypoint/filesystem plugins. `loader.py` loads plugin code. `registry.py` stores active plugins. `control_plane.py` handles enable/disable. `runtime_api.py` is the API surface exposed to plugins. `selection_pipeline.py` filters plugins by context. `state_store.py` persists enable/disable state to JSON.

### skill/
L2 Skill orchestration. `orchestrator.py` matches user intent to skills via keyword/semantic/hybrid triggers. `filesystem_loader.py` loads skills from markdown files. `skill_resource_loader.py` resolves skill dependencies (tools, context).

### routing/
Execution path decision. `execution_router.py` defines `ExecutionPath` enum (DIRECT_SKILL/PLAN_MODE/REACT_LOOP) and `RoutingDecision` dataclass. Actual routing logic is now prompt-driven in ReActAgent, not confidence-scoring.

### context/
Context window management. `context_facade.py` is the entry point. `window_manager.py` tracks token budget. `compression_engine.py` + `compaction.py` compress old messages. `guard_chain.py` + `guards/` enforce context limits. `budget_resolver.py` allocates tokens across sections. `builder/` assembles the final context payload.

### state/
Agent runtime state. `agent_session_pool.py` manages session pool for agent instances. `agent_worker_state.py` provides Redis-backed worker state (get/set redis client).

### workspace/
`manager.py` -- manages workspace directory structure for agent execution (file I/O, temp files).

### memory/
Agent-side memory operations. `capture.py` captures conversation data for memory. `recall.py` retrieves relevant memories. `flush.py` flushes pending memory writes.

### llm/
LLM invocation layer. `invoker.py` wraps LLM calls with retry/timeout. `token_sampler.py` estimates token counts.

### mcp/
MCP client integration. `client.py` connects to MCP servers. `registry.py` tracks available MCP tools. `adapter.py` adapts MCP tool format to agent tool format. `cancel.py` handles MCP request cancellation. `progress.py` tracks MCP operation progress. `oauth.py` + `oauth_callback.py` handle MCP OAuth flows.

### hitl/
Human-in-the-loop coordination. `coordinator.py` orchestrates HITL requests. `hitl_strategies.py` defines strategy per HITL type (clarification/decision/env_var/permission). `state_store.py` persists HITL state. `session_registry.py` tracks active HITL sessions. `recovery_service.py` recovers from interrupted HITL. `response_listener.py` waits for user responses. `ray_hitl_handler.py` bridges Ray actors to HITL system.

### Other Small Subdirectories

- `artifact/` -- `extractor.py`: extracts artifacts (files, images) from tool output
- `attachment/` -- `processor.py`: processes user-uploaded attachments for agent context
- `commands/` -- Slash command system: `parser.py` parses `/commands`, `registry.py` stores them, `builtins.py` defines built-ins, `interceptor.py` intercepts before agent processing
- `cost/` -- `tracker.py`: tracks token usage and cost per execution
- `doom_loop/` -- `detector.py`: detects agent stuck in repetitive loops, triggers intervention
- `heartbeat/` -- `runner.py` emits periodic heartbeat events during long operations. `tokens.py` for heartbeat token tracking
- `output/` -- Formatters: `code_formatter.py`, `markdown_formatter.py`, `table_formatter.py`
- `permission/` -- `manager.py` enforces tool permission rules (allow/deny/ask). `rules.py` defines permission policies
- `planning/` -- `plan_detector.py`: detects when query needs work-level planning
- `pool/` -- Agent pool system (HOT/WARM/COLD tiers). Large subsystem with own orchestrator, health checks, circuit breaker, HA, metrics, prewarm, lifecycle management
- `retry/` -- `policy.py`: retry policies for LLM calls (exponential backoff, rate limit handling)
- `session/` -- `compaction.py`: compacts old session data to reduce storage

## Forbidden

- Do NOT import from `actor/` in non-actor code -- actor code runs in Ray containers
- Do NOT bypass `EventConverter` for SSE events -- frontend depends on its output format
- Do NOT access `ToolDefinition` fields as if it were the original tool class (use `._tool_instance`)
