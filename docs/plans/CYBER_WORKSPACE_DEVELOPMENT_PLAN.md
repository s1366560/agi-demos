# Cyber Workspace Development Plan

> Architecture: `docs/architecture/CYBER_WORKSPACE_ARCHITECTURE.md`
> Date: 2026-03-26

---

## Overview

3 phases, 24 atomic commits. Each commit is independently deployable and testable.
Phase 1 must be fully complete before Phase 2 starts. Phase 3 is additive (2D SVG fallback works independently).

**Estimated effort**: Phase 1 (5-7 days), Phase 2 (3-4 days), Phase 3 (4-6 days)

---

## Phase 1: Group Chat + Agent Integration (9 commits)

**Goal**: Humans and AI agents can chat in a shared workspace via @mentions.

### Commit 1.1: Wire event publisher into WorkspaceService

**Problem**: `WorkspaceService.__init__` accepts optional `workspace_event_publisher` but API router instantiates it without one. All workspace events silently dropped.

**Files modified**:
- `src/infrastructure/adapters/primary/web/routers/workspaces.py` -- Inject Redis-backed event publisher into `get_workspace_service()` dependency
- `src/configuration/containers/project_container.py` -- Add `workspace_service()` factory method that wires the publisher

**Test**:
- `src/tests/unit/application/services/test_workspace_service.py` -- Add test: create workspace triggers event publisher callback

**Acceptance**:
- [ ] `WorkspaceService` receives a non-None `workspace_event_publisher`
- [ ] Creating/updating workspace publishes event to Redis `workspace:{id}:*`
- [ ] `workspace_handler.py` bridge delivers event to subscribed WebSocket clients
- [ ] Existing workspace CRUD tests still pass

---

### Commit 1.2: WorkspaceMessage domain model + repository port

**Files created**:
- `src/domain/model/workspace/workspace_message.py` -- `WorkspaceMessage` dataclass:
  ```python
  @dataclass(kw_only=True)
  class WorkspaceMessage:
      id: str = field(default_factory=lambda: str(uuid.uuid4()))
      workspace_id: str
      sender_id: str           # user_id or workspace_agent_id
      sender_type: str         # "human" | "agent"
      sender_name: str         # display name
      content: str
      mentions: list[str] = field(default_factory=list)  # list of mentioned agent/user IDs
      parent_id: str | None = None   # for threading (future)
      created_at: datetime = field(default_factory=datetime.utcnow)
  ```
- `src/domain/ports/repositories/workspace/workspace_message_repository.py` -- Port interface:
  - `save(message: WorkspaceMessage) -> None`
  - `find_by_workspace(workspace_id: str, limit: int, before: datetime | None) -> list[WorkspaceMessage]`
  - `find_mentions(workspace_id: str, target_id: str, limit: int) -> list[WorkspaceMessage]`
- `src/domain/model/workspace/__init__.py` -- Export WorkspaceMessage

**Test**:
- `src/tests/unit/domain/model/workspace/test_workspace_message.py` -- Dataclass creation, mention parsing, validation

**Acceptance**:
- [ ] `WorkspaceMessage` instantiates with all required fields
- [ ] `mentions` list populated correctly
- [ ] Unit tests pass

---

### Commit 1.3: WorkspaceMessage ORM model + SQL repository + migration

**Files created**:
- `src/infrastructure/adapters/secondary/persistence/sql_workspace_message_repository.py` -- SQL implementation of message repository
- `alembic/versions/xxxx_add_workspace_messages_table.py` -- Alembic migration

**Files modified**:
- `src/infrastructure/adapters/secondary/persistence/models.py` -- Add `WorkspaceMessageModel`:
  ```python
  class WorkspaceMessageModel(Base):
      __tablename__ = "workspace_messages"
      id = Column(String, primary_key=True)
      workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True)
      sender_id = Column(String, nullable=False)
      sender_type = Column(String, nullable=False)  # "human" | "agent"
      sender_name = Column(String, nullable=False)
      content = Column(Text, nullable=False)
      mentions = Column(JSON, nullable=False, default=list)
      parent_id = Column(String, nullable=True)
      created_at = Column(DateTime, nullable=False, index=True)
  ```
- `src/configuration/containers/project_container.py` -- Add `workspace_message_repository()` factory
- `src/configuration/di_container.py` -- Wire through to DIContainer

**Test**:
- `src/tests/integration/test_workspace_message_repository.py` -- CRUD: save, find_by_workspace (pagination), find_mentions

**Acceptance**:
- [ ] Migration applies cleanly (`alembic upgrade head`)
- [ ] `SqlWorkspaceMessageRepository` implements all port methods
- [ ] Integration tests pass with real DB session
- [ ] `alembic downgrade -1` works

---

### Commit 1.4: WorkspaceMessageService + @mention parsing

**Files created**:
- `src/application/services/workspace_message_service.py`:
  - `send_message(workspace_id, sender_id, sender_type, sender_name, content) -> WorkspaceMessage`
    - Parses `@agent-name` / `@user-name` patterns from content
    - Resolves names to IDs via workspace member/agent repos
    - Saves message via repository
    - Publishes `workspace_message_created` event via Redis
    - Returns message with populated mentions list
  - `list_messages(workspace_id, limit, before) -> list[WorkspaceMessage]`
  - `get_mentions(workspace_id, target_id, limit) -> list[WorkspaceMessage]`

**Files modified**:
- `src/configuration/containers/project_container.py` -- Add `workspace_message_service()` factory

**Test**:
- `src/tests/unit/application/services/test_workspace_message_service.py`:
  - `test_send_message_parses_mentions` -- Content with `@agent-1` extracts correct mention IDs
  - `test_send_message_publishes_event` -- Event publisher called with correct payload
  - `test_send_message_unknown_mention_ignored` -- `@nonexistent` doesn't cause error
  - `test_list_messages_pagination` -- Cursor-based pagination works

**Acceptance**:
- [ ] @mention regex correctly parses `@name` patterns (handles spaces, hyphens, underscores)
- [ ] Mention resolution maps display names to workspace member/agent IDs
- [ ] Redis event published with type `workspace_message_created`
- [ ] All unit tests pass with mocked repos

---

### Commit 1.5: Chat API endpoints

**Files created**:
- `src/infrastructure/adapters/primary/web/routers/workspace_chat.py`:
  - `POST /.../workspaces/{workspace_id}/messages` -- Send message
  - `GET /.../workspaces/{workspace_id}/messages` -- List messages (paginated, query: limit, before)
  - `GET /.../workspaces/{workspace_id}/messages/mentions/{target_id}` -- Get mentions for a user/agent

**Files modified**:
- `src/infrastructure/adapters/primary/web/main.py` -- Register `workspace_chat.router`

**Test**:
- `src/tests/integration/test_workspace_chat_api.py`:
  - `test_send_message_returns_201`
  - `test_list_messages_returns_paginated`
  - `test_send_message_unauthorized_returns_403`
  - `test_send_message_nonmember_returns_403`

**Acceptance**:
- [ ] Endpoints reachable via Swagger UI
- [ ] Auth enforced (only workspace members can send/read)
- [ ] Pagination works (limit + before cursor)
- [ ] Integration tests pass

---

### Commit 1.6: Chat frontend panel

**Files created**:
- `web/src/components/workspace/chat/ChatPanel.tsx` -- Chat panel with message list + input
- `web/src/components/workspace/chat/ChatMessage.tsx` -- Message bubble (human vs agent styling)
- `web/src/components/workspace/chat/MentionInput.tsx` -- Input with @mention autocomplete (uses workspace agent/member list)

**Files modified**:
- `web/src/services/workspaceService.ts` -- Add `sendMessage()`, `listMessages()`, `getMentions()`
- `web/src/stores/workspace.ts` -- Add chat state: `messages[]`, `sendMessage()`, `loadMessages()`, WS handler for `workspace_message_created`
- `web/src/types/workspace.ts` -- Add `WorkspaceMessage` type
- `web/src/pages/tenant/WorkspaceDetail.tsx` -- Add ChatPanel as side panel or tab

**Acceptance**:
- [ ] Chat panel renders message history
- [ ] Can type and send messages
- [ ] @mention autocomplete shows workspace agents and members
- [ ] Real-time: new messages appear via WebSocket without refresh
- [ ] Messages distinguish human vs agent senders visually

---

### Commit 1.7: Agent workspace context injection

**Problem**: When an agent is bound to a workspace, it has no awareness of workspace context.

**Files modified**:
- `src/infrastructure/agent/core/react_agent.py` -- In `_build_system_prompt()`, if agent has workspace_id:
  - Fetch workspace members, recent messages (last 20), active blackboard posts
  - Append structured context block to system prompt
  - Include delegation instructions: "Use `delegate:<agent-name>` to pass tasks"

**Files created**:
- `src/infrastructure/agent/workspace/workspace_context_builder.py`:
  - `async build_context(workspace_id, agent_id) -> str` -- Fetches and formats workspace context block
  - Uses repos to get members, messages, blackboard posts

**Test**:
- `src/tests/unit/infrastructure/agent/workspace/test_workspace_context_builder.py`:
  - `test_context_includes_members`
  - `test_context_includes_recent_messages`
  - `test_context_truncates_long_history`

**Acceptance**:
- [ ] Agent system prompt includes workspace context when workspace_id is set
- [ ] Context block is <2000 tokens (truncation works)
- [ ] Agent can reference workspace members by name in its responses

---

### Commit 1.8: workspace_chat_tool for agents

**Files created**:
- `src/infrastructure/agent/tools/workspace_chat_tool.py`:
  - `WorkspaceChatTool` -- Allows agent to post messages to workspace chat
  - Parameters: `content: str` (message text)
  - Uses `WorkspaceMessageService.send_message()` with sender_type="agent"
  - Emits `workspace_message_created` event

**Files modified**:
- `src/infrastructure/agent/core/tool_converter.py` -- Register workspace_chat_tool when agent has workspace_id

**Test**:
- `src/tests/unit/infrastructure/agent/tools/test_workspace_chat_tool.py`:
  - `test_post_message_creates_workspace_message`
  - `test_tool_schema_valid`

**Acceptance**:
- [ ] Agent can call `workspace_chat` tool to post to workspace
- [ ] Message appears in chat panel in real-time
- [ ] Tool only available to agents bound to a workspace

---

### Commit 1.9: @mention routing (message → agent trigger)

**Problem**: When a human types `@agent-name` in chat, the mentioned agent should be triggered.

**Files modified**:
- `src/application/services/workspace_message_service.py` -- After saving message with agent mentions:
  - For each mentioned agent: create/resume agent session with message as input
  - Inject workspace context via `workspace_context_builder`
  - Agent response flows back as a new `WorkspaceMessage` with sender_type="agent"

**Files modified**:
- `src/infrastructure/adapters/primary/web/websocket/handlers/workspace_handler.py` -- Add handler for `workspace_chat_send` message type (alternative to REST endpoint for real-time chat)

**Test**:
- `src/tests/unit/application/services/test_workspace_message_service.py`:
  - `test_mention_triggers_agent_session`
  - `test_mention_multiple_agents`
  - `test_agent_response_creates_message`

**Acceptance**:
- [ ] Sending `@CodeReviewer please review auth.py` triggers CodeReviewer agent
- [ ] Agent's response appears as a chat message from "CodeReviewer"
- [ ] Multiple @mentions trigger multiple agents (sequential, not parallel -- v1)
- [ ] Agent errors produce an error message in chat (not silent failure)

---

## Phase 2: API Completeness + Event Pipeline (8 commits)

**Goal**: All existing domain models have API endpoints. Full event pipeline operational.

### Commit 2.1: AgentDomainEvent subclasses for workspace events

**Files modified**:
- `src/domain/events/agent_events.py` -- Add event classes for the 13 existing workspace event types:
  - `WorkspaceCreatedEvent`, `WorkspaceUpdatedEvent`, `WorkspaceDeletedEvent`
  - `WorkspaceMemberJoinedEvent`, `WorkspaceMemberLeftEvent`
  - `WorkspaceAgentBoundEvent`, `WorkspaceAgentUnboundEvent`
  - `WorkspaceTaskCreatedEvent`, `WorkspaceTaskUpdatedEvent`
  - `WorkspaceBlackboardPostCreatedEvent`, `WorkspaceBlackboardReplyCreatedEvent`
  - `WorkspaceTopologyChangedEvent`
  - `WorkspaceMessageCreatedEvent`
- `src/infrastructure/agent/events/converter.py` -- Add workspace event transformations (most are pass-through via `to_event_dict()`)

**Test**:
- `src/tests/unit/domain/events/test_workspace_events.py` -- Each event class serializes correctly

**Acceptance**:
- [ ] All 13 event types have corresponding `AgentDomainEvent` subclasses
- [ ] `EventConverter` handles workspace events without error
- [ ] Events serialize to the format expected by frontend store handlers

---

### Commit 2.2: Blackboard API endpoints

**Files created**:
- `src/infrastructure/adapters/primary/web/routers/workspace_blackboard.py`:
  - `POST /.../workspaces/{workspace_id}/blackboard/posts` -- Create post
  - `GET /.../workspaces/{workspace_id}/blackboard/posts` -- List posts
  - `GET /.../workspaces/{workspace_id}/blackboard/posts/{post_id}` -- Get post with replies
  - `POST /.../workspaces/{workspace_id}/blackboard/posts/{post_id}/replies` -- Add reply
  - `DELETE /.../workspaces/{workspace_id}/blackboard/posts/{post_id}` -- Soft delete post

**Files modified**:
- `src/infrastructure/adapters/primary/web/main.py` -- Register router
- `src/configuration/containers/project_container.py` -- Add blackboard service factory if not exists

**Test**:
- `src/tests/integration/test_workspace_blackboard_api.py` -- CRUD + auth + pagination

**Acceptance**:
- [ ] All endpoints reachable, auth enforced
- [ ] Soft delete (not physical delete)
- [ ] Posts return with nested replies
- [ ] Events published for post/reply creation

---

### Commit 2.3: Topology mutation API endpoints

**Files created**:
- `src/infrastructure/adapters/primary/web/routers/workspace_topology.py`:
  - `POST /.../workspaces/{workspace_id}/topology/nodes` -- Add node
  - `PATCH /.../workspaces/{workspace_id}/topology/nodes/{node_id}` -- Move/update node
  - `DELETE /.../workspaces/{workspace_id}/topology/nodes/{node_id}` -- Remove node
  - `POST /.../workspaces/{workspace_id}/topology/edges` -- Add edge
  - `DELETE /.../workspaces/{workspace_id}/topology/edges/{edge_id}` -- Remove edge
  - `GET /.../workspaces/{workspace_id}/topology` -- Get full topology (nodes + edges)

**Files modified**:
- `src/infrastructure/adapters/primary/web/main.py` -- Register router

**Test**:
- `src/tests/integration/test_workspace_topology_api.py` -- CRUD + validation (no duplicate positions)

**Acceptance**:
- [ ] Hex coordinate validation (q, r within grid bounds)
- [ ] No two nodes on same hex position
- [ ] `topology_changed` event published on mutation
- [ ] GET returns complete graph (nodes + edges)

---

### Commit 2.4: Task API endpoints

**Files created**:
- `src/infrastructure/adapters/primary/web/routers/workspace_tasks.py`:
  - `POST /.../workspaces/{workspace_id}/tasks` -- Create task
  - `GET /.../workspaces/{workspace_id}/tasks` -- List tasks (filter by status, assignee)
  - `PATCH /.../workspaces/{workspace_id}/tasks/{task_id}` -- Update task (status, assignee)
  - `DELETE /.../workspaces/{workspace_id}/tasks/{task_id}` -- Soft delete

**Files modified**:
- `src/infrastructure/adapters/primary/web/main.py` -- Register router

**Test**:
- `src/tests/integration/test_workspace_tasks_api.py` -- CRUD + status transitions + assignment

**Acceptance**:
- [ ] Task status transitions validated (not arbitrary)
- [ ] Assignment to workspace members/agents only
- [ ] Events published on create/update

---

### Commit 2.5: Objective + Gene API endpoints

**Files created**:
- `src/infrastructure/adapters/primary/web/routers/workspace_objectives.py` -- CRUD for CyberObjective
- `src/infrastructure/adapters/primary/web/routers/workspace_genes.py` -- CRUD for CyberGene

**Files modified**:
- `src/infrastructure/adapters/primary/web/main.py` -- Register routers

**Test**:
- `src/tests/integration/test_workspace_objectives_api.py`
- `src/tests/integration/test_workspace_genes_api.py`

**Acceptance**:
- [ ] CRUD operations work with auth
- [ ] Gene assignment to workspace members works
- [ ] Events published

---

### Commit 2.6: Redis event publishing from all workspace services

**Files modified**:
- `src/application/services/workspace_service.py` -- Ensure ALL mutations publish events (not just workspace create)
- `src/application/services/workspace_task_service.py` -- Publish task events
- All new services from Phase 1-2 -- Verify event publishing

**Test**:
- `src/tests/unit/application/services/test_workspace_event_publishing.py` -- Mock Redis publisher, verify all service methods emit correct event types

**Acceptance**:
- [ ] Every workspace mutation (create/update/delete for all entities) publishes to Redis
- [ ] Event payload matches `AgentDomainEvent.to_event_dict()` format
- [ ] `workspace_handler.py` delivers all event types to WebSocket clients

---

### Commit 2.7: Frontend service + store completion

**Files modified**:
- `web/src/services/workspaceService.ts` -- Add API methods for: blackboard (post/reply CRUD), topology (node/edge CRUD), tasks (CRUD), objectives (CRUD), genes (CRUD)
- `web/src/stores/workspace.ts` -- Add event handlers for all workspace event types. Verify all 13 WS event types route to correct store updates.
- `web/src/types/workspace.ts` -- Add any missing types

**Acceptance**:
- [ ] All API methods typed and working
- [ ] All 13 WS event types handled in store
- [ ] BlackboardPanel, TaskBoard, ObjectiveList, GeneList all functional with real API data

---

### Commit 2.8: delegate/escalate protocol

**Files modified**:
- `src/infrastructure/agent/processor/processor.py` -- After tool execution or agent response, scan output for `delegate:<agent-name>` and `escalate:<agent-name>` patterns
- `src/application/services/workspace_message_service.py` -- Add `delegate_to_agent(from_agent_id, to_agent_name, context)` method

**Test**:
- `src/tests/unit/infrastructure/agent/processor/test_delegate_escalate.py`:
  - `test_delegate_pattern_detected`
  - `test_escalate_pattern_detected`
  - `test_unknown_target_produces_error_message`

**Acceptance**:
- [ ] Agent output containing `delegate:CodeReviewer` forwards task to CodeReviewer
- [ ] Delegation creates a chat message visible to all workspace participants
- [ ] Unknown target produces human-readable error in chat
- [ ] Escalation includes full conversation context

---

## Phase 3: 3D Visualization (7 commits)

**Goal**: Optional 3D hex topology view using R3F. 2D SVG remains as default/fallback.

**Prerequisites**: `pnpm add @react-three/fiber @react-three/drei three three-mesh-bvh`

### Commit 3.1: R3F setup + boilerplate

**Files created**:
- `web/src/components/workspace/hex3d/HexGrid3D.tsx` -- R3F Canvas with basic scene (camera, lights, OrbitControls)
- `web/src/components/workspace/hex3d/HexScene.tsx` -- Scene graph root (receives topology data as props)

**Files modified**:
- `web/package.json` -- Add `@react-three/fiber`, `@react-three/drei`, `three`, `@types/three`, `three-mesh-bvh`

**Acceptance**:
- [ ] R3F Canvas renders without errors
- [ ] OrbitControls work (pan, zoom, rotate)
- [ ] No StrictMode double-render issues (R3F v9+ StrictMode fix)

---

### Commit 3.2: 3D hex grid with InstancedMesh

**Files created**:
- `web/src/components/workspace/hex3d/HexInstances.tsx` -- InstancedMesh rendering all hex cells
  - Uses `useHexLayout` hook (shared with 2D) for hex coordinates
  - Single InstancedMesh with flat-top hex geometry
  - Color-coded by node type (empty, occupied, corridor)

**Test**: Visual verification -- screenshot comparison

**Acceptance**:
- [ ] 100+ hexes render in single draw call (verify via R3F stats)
- [ ] Hex positions match 2D layout exactly
- [ ] Node type colors match design spec

---

### Commit 3.3: 3D agent mesh

**Files created**:
- `web/src/components/workspace/hex3d/AgentMesh.tsx` -- 3D agent representation on hex grid
  - Simple geometric avatar (cylinder body + sphere head, color-coded)
  - Positioned on assigned hex node
  - Idle animation (gentle bob/rotation)
  - Name label via `@react-three/drei` `<Html>` or `<Billboard>`

**Acceptance**:
- [ ] Agents render at correct hex positions
- [ ] Agent color matches workspace agent config
- [ ] Name label readable from all camera angles
- [ ] Idle animation smooth at 60fps

---

### Commit 3.4: 3D corridor mesh

**Files created**:
- `web/src/components/workspace/hex3d/CorridorMesh.tsx` -- Tube/pipe geometry connecting hex nodes
  - Uses `TopologyEdge` data to connect source → target hexes
  - `@react-three/drei` `<Line>` or custom TubeGeometry
  - Animated flow particles (optional, gated by performance)

**Acceptance**:
- [ ] Corridors connect correct hex pairs
- [ ] Visual distinct from hex surfaces
- [ ] No z-fighting with hex meshes

---

### Commit 3.5: Raycasting + hex interaction

**Files modified**:
- `web/src/components/workspace/hex3d/HexInstances.tsx` -- Add raycasting via `three-mesh-bvh`
  - Click to select hex
  - Hover to highlight
  - Right-click for context menu

**Files modified**:
- `web/src/components/workspace/hex3d/HexGrid3D.tsx` -- Wire interaction callbacks (onSelectHex, onContextMenu) matching 2D HexGrid API

**Acceptance**:
- [ ] Click selects hex (highlight + callback)
- [ ] Hover shows tooltip with hex info
- [ ] Context menu positioned correctly in screen space
- [ ] Raycasting performs well with 100+ hexes (BVH)

---

### Commit 3.6: Camera controls + zoom-to-agent

**Files modified**:
- `web/src/components/workspace/hex3d/HexGrid3D.tsx`:
  - "Zoom to agent" button -- smooth camera animation to agent's hex position
  - Minimap overlay (using `@react-three/drei` `<PerspectiveCamera>` or 2D `HexMiniMap` overlay)
  - Camera bounds (prevent zoom too far in/out)

**Acceptance**:
- [ ] Zoom-to-agent smooth animation (~500ms)
- [ ] Camera bounds prevent losing the grid
- [ ] Minimap shows current viewport position

---

### Commit 3.7: 2D/3D toggle + WorkspaceDetail integration

**Files modified**:
- `web/src/pages/tenant/WorkspaceDetail.tsx`:
  - Toggle button: "2D" / "3D" view (persisted in localStorage)
  - Lazy load `HexGrid3D` only when 3D mode selected
  - Both views receive same props (agents, nodes, edges, objectives, callbacks)

**Acceptance**:
- [ ] Toggle switches view without losing state
- [ ] 3D component lazy-loaded (no bundle impact when using 2D)
- [ ] Both views display identical data
- [ ] Default is 2D (accessible, mobile-friendly)

---

## Quality Gates

### Per-Commit Requirements

1. **TDD**: Write test BEFORE implementation. Test file committed in same commit as implementation.
2. **Diagnostics clean**: `lsp_diagnostics` clean on all changed files. Zero new type errors.
3. **Existing tests pass**: `make test-unit` green before and after commit.
4. **Backend format/lint**: `make format-backend && make lint-backend` clean.
5. **Frontend lint**: `pnpm lint` clean (for frontend changes).

### Per-Phase Requirements

1. **Phase 1 complete**: Human can send chat message, @mention triggers agent, agent responds in chat. Full round-trip working.
2. **Phase 2 complete**: All workspace entity types have CRUD API endpoints. All events flow from service → Redis → WebSocket → frontend store.
3. **Phase 3 complete**: 3D hex grid renders with agents, corridors, interaction. Toggle between 2D/3D.

### Integration Test Scenarios

| Scenario | Phase | Steps |
|----------|-------|-------|
| Human sends chat message | 1 | POST /messages → 201, message in DB, event via WS, appears in frontend |
| @mention triggers agent | 1 | POST message with `@AgentName` → agent session created → agent response as new message |
| Agent delegates to agent | 1 | Agent output with `delegate:OtherAgent` → forwarding message → OtherAgent triggered |
| Blackboard post with reply | 2 | POST post → POST reply → GET post returns post + reply |
| Topology mutation | 2 | POST node → PATCH move → GET topology correct |
| Full event pipeline | 2 | Any mutation → Redis Stream → WS handler → frontend store update |
| 3D render | 3 | Toggle to 3D → Canvas renders → click hex → callback fires |

---

## Appendix: Commit Dependency Graph

```
1.1 (event publisher wiring)
 └── 1.2 (WorkspaceMessage model)
      └── 1.3 (ORM + SQL repo + migration)
           └── 1.4 (message service + @mention parse)
                ├── 1.5 (chat API endpoints)
                │    └── 1.6 (chat frontend)
                ├── 1.7 (agent context injection)
                │    └── 1.9 (@mention → agent trigger)
                └── 1.8 (workspace_chat_tool)
                     └── 1.9 (delegate/escalate)

2.1 (event subclasses)  ← can start parallel with 1.x after 1.1
2.2 (blackboard API)    ← independent
2.3 (topology API)      ← independent
2.4 (task API)          ← independent
2.5 (objective+gene API) ← independent
2.6 (event publishing)  ← depends on 2.1
2.7 (frontend completion) ← depends on 2.2-2.5
2.8 (delegate/escalate) ← depends on 1.9

3.1-3.7                 ← all depend on Phase 2 complete
```
