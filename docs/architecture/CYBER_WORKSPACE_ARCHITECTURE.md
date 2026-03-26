# Cyber Workspace (赛博办公室) Architecture Design

> Reference: `/Users/tiejunsun/github/nodeskclaw` (DeskClaw)
> Target: `/Users/tiejunsun/github/agi-demos` (MemStack)
> Date: 2026-03-26

---

## 1. Executive Summary

The Cyber Workspace is a human-AI collaborative space where humans and AI agents work together as peers. Agents occupy hex-topology positions, participate in group chat via @mentions, post to shared blackboards, and execute delegated tasks -- all visible in a 3D visualization.

**Key insight: ~60% of the infrastructure already exists.** This document focuses on the **gaps** between what DeskClaw specifies and what MemStack already has.

### What Already Exists (DO NOT rebuild)

| Layer | Existing Infrastructure | Files |
|-------|------------------------|-------|
| Domain Models | 13 models: Workspace, WorkspaceMember, WorkspaceAgent, WorkspaceTask, BlackboardPost, BlackboardReply, TopologyNode, TopologyEdge, CyberObjective, CyberGene, hex_utils, workspace_role, workspace_permissions | `src/domain/model/workspace/` |
| Repository Ports | All CRUD interfaces for workspace entities | `src/domain/ports/repositories/workspace/` |
| SQL Repositories | 8 implementations with `_to_domain/_to_db/_update_fields` | `src/infrastructure/adapters/secondary/persistence/sql_workspace_*.py` |
| ORM Models | 10 SQLAlchemy models (WorkspaceModel through CyberGeneModel) | `models.py` lines 262-2220 |
| Application Services | WorkspaceService, WorkspaceTaskService, WorkspacePresenceService, WorkspaceSyncService | `src/application/services/workspace_*.py` |
| API Router | 13 endpoints: workspace CRUD, member CRUD, agent binding | `routers/workspaces.py` (552 lines) |
| WebSocket Handlers | subscribe/unsubscribe workspace, presence join/leave/heartbeat | `workspace_handler.py` |
| Event Types | 13 workspace event types in `AgentEventType` enum | `types.py` lines 287-299 |
| DI Wiring | All workspace repos wired through ProjectContainer + DIContainer | `project_container.py`, `di_container.py` |
| Migrations | 2 Alembic migrations for workspace tables + cyber_genes | `alembic/versions/` |
| Frontend Routes | `/tenant/:tenantId/workspaces` and `/tenant/:tenantId/workspaces/:workspaceId` | `App.tsx` |
| Frontend Pages | WorkspaceList.tsx (list + create), WorkspaceDetail.tsx (hex grid + tabs) | `web/src/pages/tenant/` |
| Zustand Store | Full store with state, actions, WS event handlers | `web/src/stores/workspace.ts` |
| Service Layer | REST client matching all backend router endpoints | `web/src/services/workspaceService.ts` |
| WebSocket Hook | Subscription/heartbeat/event routing to store | `web/src/hooks/useWorkspaceWebSocket.ts` |
| UI Components | 24 files: HexGrid (2D SVG), HexCell, HexAgent, HexCorridor, HexHumanSeat, HexFlowAnimation, HexTooltip, HexObjective, HexMiniMap, HexContextMenu, BlackboardPanel, TaskBoard, ObjectiveList/Card/Progress/CreateModal, GeneList/Card/AssignModal, MemberPanel, PresenceBar/Avatar, TopologyBoard | `web/src/components/workspace/` |

---

## 2. Gap Analysis Matrix

### Status Legend
- **COMPLETE**: Fully implemented, tested, production-ready
- **PARTIAL**: Core exists but missing specific features
- **STUB**: Structure exists but implementation incomplete
- **MISSING**: Not implemented at all

### 2.1 Backend Gaps

| Component | Status | What Exists | What's Missing | DeskClaw Equivalent |
|-----------|--------|-------------|----------------|---------------------|
| **WorkspaceMessage domain model** | MISSING | -- | `WorkspaceMessage` entity for group chat (sender_type: human/agent, content, @mentions, workspace_id, timestamp) | `workspace_message.py` |
| **WorkspaceMessage repository** | MISSING | -- | Port interface + SQL implementation for message CRUD, pagination, @mention queries | `workspace_message_service.py` (queries) |
| **WorkspaceMessageService** | MISSING | -- | Application service: send, list, paginate, @mention routing | `workspace_message_service.py` |
| **Chat API endpoints** | MISSING | -- | POST /messages, GET /messages (paginated), GET /messages/mentions | `api/workspaces.py` chat routes |
| **@mention routing** | MISSING | -- | Parse `@agent-name` from message content, route to appropriate agent ReAct session | `collaboration_service.py` mention_dispatch |
| **Agent-as-participant** | MISSING | WorkspaceAgent model exists (agent binding to workspace) | System prompt injection with workspace context (members, recent chat, blackboard summaries) | Runtime Platform agent context |
| **delegate/escalate protocol** | MISSING | SubAgent orchestration exists | Detect `delegate:<target>` / `escalate:<target>` patterns in agent output, forward to target agent | `collaboration_service.py` delegation |
| **Event publisher DI wiring** | PARTIAL | `WorkspaceService.__init__` accepts optional `workspace_event_publisher` callback | API router (`workspaces.py` line 30) instantiates `WorkspaceService` WITHOUT injecting a publisher. Events silently dropped. | N/A (DeskClaw uses SSE directly) |
| **Workspace AgentDomainEvent subclasses** | MISSING | 13 event type enums defined in `AgentEventType` | No corresponding `AgentDomainEvent` subclasses in `agent_events.py`. Events cannot be emitted through the standard pipeline. | N/A (DeskClaw uses SSE) |
| **Blackboard API endpoints** | MISSING | Domain models + repos + ORM exist | No API router endpoints for blackboard post/reply CRUD. Frontend has BlackboardPanel but no backend endpoints to call. | `api/workspaces.py` blackboard routes |
| **Topology mutation API** | MISSING | Domain models + repos + ORM exist | No API endpoints for add/remove/move topology nodes and edges | `api/workspaces.py` topology routes |
| **Objective/Gene API endpoints** | MISSING | Domain models + repos + ORM exist | No CRUD endpoints. Frontend has ObjectiveList/GeneList but no backend API. | `api/workspaces.py` |
| **Task API endpoints** | MISSING | WorkspaceTaskService exists | No router endpoints to expose task lifecycle (create, assign, update status) | `api/workspaces.py` task routes |
| **WorkspaceMessage ORM model** | MISSING | -- | SQLAlchemy model for workspace_messages table | N/A |
| **WorkspaceMessage migration** | MISSING | -- | Alembic migration adding workspace_messages table | N/A |

### 2.2 Frontend Gaps

| Component | Status | What Exists | What's Missing | DeskClaw Equivalent |
|-----------|--------|-------------|----------------|---------------------|
| **HexGrid 3D (R3F)** | MISSING | 2D SVG HexGrid (420 lines) with pan/zoom/drag | R3F-based 3D hex topology with InstancedMesh, orbit controls, raycasting | `Workspace3D.vue` |
| **Chat panel** | MISSING | -- | Group chat UI: message list, input, @mention autocomplete, agent/human avatars | DeskClaw chat sidebar |
| **3D agent mesh** | MISSING | 2D HexAgent SVG component | 3D robot/avatar mesh for agents on hex grid | `Grabby.ts` |
| **3D corridor paths** | MISSING | 2D HexCorridor SVG component | 3D corridor mesh connecting hex nodes | `CorridorPath.ts` |
| **Workspace service: chat endpoints** | MISSING | workspaceService.ts covers CRUD/member/agent | No chat message API methods | N/A |
| **Workspace service: blackboard endpoints** | MISSING | -- | No blackboard post/reply API methods | N/A |
| **Workspace service: topology endpoints** | MISSING | -- | No topology node/edge mutation API methods | N/A |
| **Workspace store: chat state** | MISSING | Store handles presence/task/topology/blackboard/gene events | No chat message state, send action, or event handler | N/A |

### 2.3 Integration Gaps

| Integration Point | Status | What Exists | What's Missing |
|-------------------|--------|-------------|----------------|
| **Agent → WorkspaceMessage** | MISSING | SubAgent announce_service delivers results | No path from agent tool output to workspace chat message |
| **WorkspaceMessage → Agent** | MISSING | ReActAgent has workspace_manager (persona loader) | No path from @mention in chat to triggering agent session |
| **Redis Streams workspace events** | PARTIAL | `workspace_handler.py` bridges Redis `workspace:{id}:*` to WS clients | Only presence events published. No chat/blackboard/topology events published to Redis. |
| **WebSocket event delivery** | PARTIAL | `workspace_handler.py` forwards events from Redis to subscribed clients | Event publisher not injected (see above), so no events flow through the pipeline |

---

## 3. System Architecture

### 3.1 Page Integration

The Cyber Workspace lives at `/tenant/:tenantId/workspaces/:workspaceId` as a **separate page** alongside the existing AgentWorkspace at `/tenant/:tenantId/agent`. They share the agent runtime but have different UIs and interaction models.

```
Existing:  /tenant/:tenantId/agent              → AgentWorkspace (1:1 human-agent chat)
New:       /tenant/:tenantId/workspaces          → WorkspaceList (browse/create)
Exists:    /tenant/:tenantId/workspaces/:id      → WorkspaceDetail (cyber workspace)
```

### 3.2 Domain Model Relationships

```
Workspace (root aggregate)
├── WorkspaceMember[]        (human participants, role-based)
├── WorkspaceAgent[]         (AI agent bindings, hex position)
├── WorkspaceMessage[]       ← NEW (group chat messages)
├── BlackboardPost[]         (shared knowledge posts)
│   └── BlackboardReply[]    (threaded replies)
├── WorkspaceTask[]          (assigned work items)
├── TopologyNode[]           (hex grid positions)
│   └── TopologyEdge[]       (connections between nodes)
├── CyberObjective[]         (workspace goals)
└── CyberGene[]              (workspace behavior genes)
```

### 3.3 Event Flow Architecture

```
                                  ┌──────────────────────────────┐
                                  │        Frontend (React)       │
                                  │  ┌──────────────────────────┐ │
                                  │  │   useWorkspaceWebSocket  │ │
                                  │  │   ↓ events to store      │ │
                                  │  │   workspace.ts (Zustand)  │ │
                                  │  └──────────────────────────┘ │
                                  └──────────▲───────────────────┘
                                             │ WebSocket
                                             │
┌──────────────────────┐         ┌───────────┴──────────────────┐
│   WorkspaceService   │  Redis  │    workspace_handler.py      │
│   (publish event)    │ ──────→ │    (bridge: Redis → WS)      │
│                      │ Streams │                               │
└──────────────────────┘         └──────────────────────────────┘
         ▲                                    
         │                       ┌──────────────────────────────┐
         │                       │   ReActAgent (workspace)     │
         │  agent output         │   ↓ @mention detected        │
         │  → workspace msg      │   ↓ delegate/escalate        │
         │                       │   → WorkspaceMessageService  │
         └───────────────────────┴──────────────────────────────┘
```

### 3.4 Agent-as-Workspace-Participant Architecture

Workspace agents are standard `ReActAgent` instances. No new runtime. Integration points:

1. **System prompt injection**: When an agent is bound to a workspace, its system prompt is augmented with:
   - Workspace member list (humans + other agents)
   - Recent chat messages (last N)
   - Active blackboard posts
   - Current topology context (agent's hex position + neighbors)

2. **@mention trigger**: When a chat message contains `@agent-name`:
   - `WorkspaceMessageService` parses mentions
   - Creates/resumes a `ReActAgent` session for the mentioned agent
   - Injects the message as user input with workspace context
   - Agent response is written back as a `WorkspaceMessage` with `sender_type=agent`

3. **delegate/escalate**: When an agent's output contains `delegate:<agent-name>` or `escalate:<agent-name>`:
   - The processor detects the pattern (similar to existing SubAgent delegation)
   - Creates a `WorkspaceMessage` forwarding the task to the target agent
   - Target agent is triggered via @mention mechanism

```
┌────────────────────────────────────────────────────────┐
│                     ReActAgent                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │ System Prompt                                   │   │
│  │ + workspace_context_block:                      │   │
│  │   - members: [{name, role, status}]             │   │
│  │   - recent_chat: [{sender, content, time}]      │   │
│  │   - blackboard: [{title, content}]              │   │
│  │   - my_position: {q, r, neighbors}              │   │
│  │   - delegation: "Use delegate:<name> to ..."    │   │
│  └─────────────────────────────────────────────────┘   │
│                                                        │
│  Tools: [existing tools] + workspace_chat_tool         │
│  (workspace_chat_tool: post message to workspace chat) │
└────────────────────────────────────────────────────────┘
```

---

## 4. Technology Decisions

| Decision | Choice | Rationale | Alternatives Rejected |
|----------|--------|-----------|----------------------|
| 3D Framework | `@react-three/fiber` v9+ | Declarative JSX, Zustand integration, 30K+ stars, active maintenance | Raw Three.js (imperative, harder to maintain in React) |
| Hex rendering | `InstancedMesh` + `three-mesh-bvh` | Single draw call for 100+ hexes, BVH for efficient raycasting | Individual mesh per hex (O(n) draw calls) |
| Message queue | Extend Redis Streams | Already in stack (`RedisUnifiedEventBusAdapter`); PGMQ adds unnecessary PG extension + operational burden | PGMQ (DeskClaw pattern — requires PG extension) |
| Real-time delivery | Extend existing WebSocket | `workspace_handler.py` already bridges Redis → WS clients. `TopicType.WORKSPACE` already defined. | SSE (DeskClaw pattern — would duplicate WS infra) |
| Agent runtime | ReActAgent + workspace config | No new runtime. Add workspace context to system prompt + workspace_chat_tool | New "WorkspaceAgent" runtime (unnecessary abstraction) |
| Frontend migration | Redesign for React idioms | Vue composables != React hooks, Pinia != Zustand. Line-by-line port produces non-idiomatic code. | Vue → React component port (produces Frankenstein code) |
| 2D fallback | Keep existing 2D SVG HexGrid | Already complete (420 lines, pan/zoom/drag/minimap). 3D is additive, not replacement. | Remove 2D (loses accessibility, mobile support) |
| Chat storage | PostgreSQL (workspace_messages table) | Consistent with all other workspace entities. Redis Streams for delivery, PG for persistence. | Redis-only (no durable history) |

---

## 5. Constraints and Anti-Patterns

### 5.1 Hard Constraints (from AGENTS.md)

- NEVER modify database directly -- always use Alembic migrations
- NEVER call `app.state.container.some_service()` for DB-dependent services
- Repository interfaces accept and return DOMAIN entities, never SQLAlchemy models
- Do NOT bypass `EventConverter` for SSE events
- Do NOT import from `actor/` in non-actor code

### 5.2 Anti-Patterns (from Metis analysis)

| DO NOT | Why |
|--------|-----|
| Create abstract `BaseWorkspaceMember` class | Just use a `role: Literal["human", "agent"]` field or existing separate models |
| Build a "workspace event bus" abstraction | Use Redis Streams directly via existing `RedisUnifiedEventBusAdapter` |
| Create "workspace middleware" layers | Direct service calls, no middleware chain |
| Add more than 13 workspace event types without user approval | Scope control -- existing 13 types cover all known use cases |
| Build 3D visualization before chat is complete and tested | 3D is Phase 3. Chat + agent integration is the foundation. |
| Port DeskClaw Vue components line-by-line | Redesign for React/Zustand/Ant Design idioms |

### 5.3 Risk Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Scope explosion (8+ subsystems) | Critical | Strict 3-phase plan. Phase 1 must be complete before starting Phase 2. |
| 3D as distraction | High | 3D is Phase 3 only. 2D SVG fallback already exists and works. |
| Multi-agent state race conditions | Medium | One agent per workspace session at a time (initial). Queue concurrent @mentions. |
| Event publisher not wired | Medium | Phase 1 Commit 1 -- fix before any other work. |

---

## 6. File Inventory for Implementation

### 6.1 New Files to Create

```
# Domain Layer
src/domain/model/workspace/workspace_message.py           # WorkspaceMessage entity
src/domain/ports/repositories/workspace/workspace_message_repository.py  # Port interface

# Infrastructure Layer
src/infrastructure/adapters/secondary/persistence/sql_workspace_message_repository.py  # SQL impl

# Application Layer
src/application/services/workspace_message_service.py      # Chat service

# API Layer
src/infrastructure/adapters/primary/web/routers/workspace_chat.py       # Chat endpoints
src/infrastructure/adapters/primary/web/routers/workspace_blackboard.py # Blackboard endpoints
src/infrastructure/adapters/primary/web/routers/workspace_topology.py   # Topology endpoints
src/infrastructure/adapters/primary/web/routers/workspace_tasks.py      # Task endpoints
src/infrastructure/adapters/primary/web/routers/workspace_objectives.py # Objective endpoints
src/infrastructure/adapters/primary/web/routers/workspace_genes.py      # Gene endpoints

# Agent Integration
src/infrastructure/agent/tools/workspace_chat_tool.py      # Agent tool: post to workspace chat

# Alembic
alembic/versions/xxxx_add_workspace_messages_table.py      # Migration

# Frontend
web/src/components/workspace/chat/ChatPanel.tsx            # Chat UI
web/src/components/workspace/chat/ChatMessage.tsx           # Message bubble
web/src/components/workspace/chat/MentionInput.tsx          # @mention autocomplete input
web/src/components/workspace/hex3d/HexGrid3D.tsx           # R3F 3D hex grid (Phase 3)
web/src/components/workspace/hex3d/AgentMesh.tsx           # 3D agent avatar (Phase 3)
web/src/components/workspace/hex3d/CorridorMesh.tsx        # 3D corridor (Phase 3)

# Tests
src/tests/unit/domain/model/workspace/test_workspace_message.py
src/tests/unit/application/services/test_workspace_message_service.py
src/tests/integration/test_workspace_chat_api.py
```

### 6.2 Files to Modify

```
# Event Publisher Wiring
src/infrastructure/adapters/primary/web/routers/workspaces.py  # Inject event publisher into WorkspaceService
src/configuration/containers/project_container.py              # Add workspace_message_repository, workspace_service with publisher

# Event Classes
src/domain/events/agent_events.py                            # Add workspace AgentDomainEvent subclasses
src/infrastructure/agent/events/converter.py                  # Add workspace event transformations

# ORM
src/infrastructure/adapters/secondary/persistence/models.py  # Add WorkspaceMessageModel

# Agent Integration
src/infrastructure/agent/core/react_agent.py                 # Inject workspace context into system prompt
src/infrastructure/agent/processor/processor.py              # Detect delegate/escalate patterns
src/infrastructure/agent/core/tool_converter.py              # Register workspace_chat_tool

# WebSocket
src/infrastructure/adapters/primary/web/websocket/handlers/workspace_handler.py  # Add chat event handling

# Frontend
web/src/stores/workspace.ts                                  # Add chat state + actions
web/src/services/workspaceService.ts                         # Add chat/blackboard/topology API methods
web/src/pages/tenant/WorkspaceDetail.tsx                     # Add chat panel, integrate 3D toggle
web/src/types/workspace.ts                                   # Add WorkspaceMessage type

# App Registration
src/infrastructure/adapters/primary/web/main.py              # Register new routers
```

---

## 7. Dependency Graph

```
Phase 1 (Foundation: Chat + Agent Integration)
├── 1.1 Event publisher wiring (unblocks ALL events)
├── 1.2 WorkspaceMessage model + repo + ORM + migration
├── 1.3 WorkspaceMessageService (depends on 1.2)
├── 1.4 Chat API endpoints (depends on 1.3)
├── 1.5 Chat frontend panel (depends on 1.4)
├── 1.6 @mention routing (depends on 1.3)
├── 1.7 Agent workspace context injection (depends on 1.6)
├── 1.8 workspace_chat_tool for agents (depends on 1.3)
└── 1.9 delegate/escalate protocol (depends on 1.7, 1.8)

Phase 2 (Completeness: Missing API Endpoints + Events)
├── 2.1 Blackboard API endpoints
├── 2.2 Topology mutation API endpoints
├── 2.3 Task API endpoints
├── 2.4 Objective API endpoints
├── 2.5 Gene API endpoints
├── 2.6 AgentDomainEvent subclasses for workspace events
├── 2.7 Redis event publishing from all services
└── 2.8 Frontend store event handler completion

Phase 3 (3D Visualization)
├── 3.1 R3F setup (@react-three/fiber + @react-three/drei)
├── 3.2 3D HexGrid with InstancedMesh
├── 3.3 3D AgentMesh (robot avatar)
├── 3.4 3D CorridorMesh
├── 3.5 Raycasting + hex interaction
├── 3.6 Camera controls (orbit, zoom to agent)
├── 3.7 2D/3D toggle in WorkspaceDetail
└── 3.8 Performance optimization (BVH, LOD)
```

---

## 8. Appendix: DeskClaw Reference Architecture

For context, DeskClaw implements the following (used as specification, NOT code to port):

- **Backend**: FastAPI + PostgreSQL + PGMQ message queue + 5-layer Runtime Platform
- **Frontend**: Vue 3 + Pinia + Three.js (raw) + SSE for real-time
- **Key patterns**: Tunnel-based agent communication, 8-layer message middleware, PGMQ for reliable delivery
- **We adapt**: Concept of hex topology, agent-as-workspace-participant, blackboard system, group chat with @mentions
- **We replace**: PGMQ → Redis Streams, SSE → WebSocket, Vue/Pinia → React/Zustand, Raw Three.js → R3F, Tunnel → Direct ReActAgent integration
