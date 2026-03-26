# CyberOffice Development Plan

> Status: DRAFT | Version: 1.0 | Date: 2026-03-25
> Architecture doc: `cyber-office-architecture.md`

## Summary

6-phase implementation plan to add CyberOffice features to MemStack by extending the existing workspace infrastructure. Each phase is self-contained and shippable.

**Strategy: EXTEND existing workspace infrastructure, NOT rebuild.**

---

## Phase 0: Foundation (Domain Model Extensions + Migration)

**Goal**: Extend all backend domain models, ORM, repositories, and API schemas to support hex positioning, OKR objectives, and enhanced task management. No frontend changes yet.

### Phase 0 Tasks

#### 0.1 Hex Utility Module
- **File**: `src/domain/model/workspace/hex_utils.py` (NEW)
- **Action**: Create pure domain utility functions for hex coordinate math
- **Content**: `ADJACENT_OFFSETS`, `is_adjacent()`, `hex_distance()`, `hex_neighbors()`, `hex_to_pixel()`, `pixel_to_hex()`, `_axial_round()`
- **Verify**: `uv run pytest src/tests/unit/test_hex_utils.py -v` (write unit test alongside)

#### 0.2 Extend Domain Models
- **Files to modify**:
  - `src/domain/model/workspace/workspace.py` -- add `office_status: str`, `hex_layout_config: dict[str, Any]`
  - `src/domain/model/workspace/workspace_agent.py` -- add `hex_q: int`, `hex_r: int`, `label: str | None`, `theme_color: str | None`, `status: str`
  - `src/domain/model/workspace/topology_node.py` -- add `hex_q: int | None`, `hex_r: int | None`, `status: str`, `tags: list[str]`; extend `TopologyNodeType` enum with `CORRIDOR`, `HUMAN_SEAT`, `OBJECTIVE`
  - `src/domain/model/workspace/topology_edge.py` -- add `source_hex_q: int | None`, `source_hex_r: int | None`, `target_hex_q: int | None`, `target_hex_r: int | None`, `direction: str | None`, `auto_created: bool`
  - `src/domain/model/workspace/workspace_task.py` -- add `priority: int`, `estimated_effort: str | None`, `blocker_reason: str | None`, `completed_at: datetime | None`, `archived_at: datetime | None`
  - `src/domain/model/workspace/__init__.py` -- export new entities
- **Verify**: `uv run ruff check src/domain/model/workspace/` + `uv run pyright src/domain/model/workspace/`

#### 0.3 New Domain Entity: CyberObjective
- **Files**:
  - `src/domain/model/workspace/cyber_objective.py` (NEW) -- `CyberObjective` dataclass + `CyberObjectiveType` enum
  - `src/domain/model/workspace/__init__.py` -- add exports
- **Verify**: ruff + pyright clean

#### 0.4 New Repository Interface: CyberObjectiveRepository
- **File**: `src/domain/ports/repositories/workspace/cyber_objective_repository.py` (NEW)
- **Methods**: `save`, `find_by_id`, `find_by_workspace`, `find_children`, `update`, `delete`
- **Also update**: `src/domain/ports/repositories/workspace/__init__.py` (if exists) or `__init__.py` closest
- **Verify**: ruff + pyright clean

#### 0.5 Extend ORM Models
- **File**: Locate existing workspace ORM models (likely in `src/infrastructure/adapters/secondary/persistence/models.py` or split files)
- **Action**: Add columns to `WorkspaceModel`, `WorkspaceAgentModel`, `TopologyNodeModel`, `TopologyEdgeModel`, `WorkspaceTaskModel`
- **New ORM model**: `CyberObjectiveModel`
- **Verify**: Models match domain entities field-for-field

#### 0.6 Extend SQL Repository Implementations
- **Files**: `sql_workspace_agent_repository.py`, `sql_topology_repository.py`, `sql_workspace_task_repository.py`
- **Action**: Update `_to_domain()` and `_to_db()` methods to map new fields
- **New file**: `sql_cyber_objective_repository.py` (NEW)
- **Verify**: ruff + pyright clean

#### 0.7 Alembic Migration
- **Command**: `PYTHONPATH=. uv run alembic revision --autogenerate -m "cyber_office_phase0_extend_workspace"`
- **Action**: Review generated migration, ensure:
  - `op.add_column` for all extended tables
  - `op.create_table` for `cyber_objectives`
  - Unique constraint on `(workspace_id, hex_q, hex_r)` for `workspace_agents`
  - Partial unique index on `topology_nodes` for hex coords (WHERE hex_q IS NOT NULL)
  - Index on `cyber_objectives(workspace_id, parent_id)`
- **Verify**: `PYTHONPATH=. uv run alembic upgrade head` succeeds

#### 0.8 API Schemas (DTOs)
- **File**: `src/application/schemas/workspace_cyber_schemas.py` (NEW)
- **Content**: `AgentPositionRequest`, `CyberObjectiveCreate`, `CyberObjectiveUpdate`, `CyberObjectiveResponse`, extended response schemas for WorkspaceAgent/TopologyNode
- **Verify**: ruff + pyright clean

#### 0.9 API Router: CyberObjective CRUD
- **File**: `src/infrastructure/adapters/primary/web/routers/cyber_objectives.py` (NEW)
- **Endpoints**: POST, GET (list), GET (single), PATCH, DELETE, PATCH progress
- **Register**: in `main.py` or router registration module
- **Verify**: `curl` test or `pytest` API test

#### 0.10 Extend Existing Routers
- **File**: `src/infrastructure/adapters/primary/web/routers/workspaces.py`
- **Action**: Add `PATCH /agents/{agent_id}/position` endpoint, `GET /agents/topology` endpoint
- **Verify**: Endpoint returns correct response

#### 0.11 DI Container Updates
- **File**: `src/configuration/di_container.py`
- **Action**: Register `CyberObjectiveRepository` -> `SqlCyberObjectiveRepository`
- **Verify**: Container resolves all workspace repositories

#### 0.12 Unit Tests for Hex Utils
- **File**: `src/tests/unit/test_hex_utils.py` (NEW)
- **Coverage**: All functions in hex_utils.py (is_adjacent, hex_distance, hex_to_pixel, pixel_to_hex, hex_neighbors)
- **Verify**: `uv run pytest src/tests/unit/test_hex_utils.py -v` all pass

### Phase 0 Verification
```bash
uv run ruff check src/domain/model/workspace/ src/application/schemas/ src/infrastructure/adapters/
uv run pyright src/domain/model/workspace/
PYTHONPATH=. uv run alembic upgrade head
uv run pytest src/tests/unit/test_hex_utils.py -v
```

### Phase 0 前端表现变化 (Frontend UI Changes)
**None.** Phase 0 is backend-only. Frontend starts in Phase 1.

---

## Phase 1: WebSocket Real-Time (Presence + Broadcasting)

**Goal**: Enable real-time workspace presence tracking and event broadcasting through the existing WebSocket infrastructure.

### Phase 1 Tasks

#### 1.1 WorkspacePresenceService
- **File**: `src/application/services/workspace_presence_service.py` (NEW)
- **Content**: `join()`, `leave()`, `get_online_users()`, `heartbeat()` methods
- **Dependencies**: Redis client, TopicManager
- **Verify**: Unit test with mocked Redis

#### 1.2 WebSocket Workspace Topic Handler
- **File**: `src/infrastructure/adapters/primary/web/websocket/workspace_handler.py` (NEW)
- **Action**: Handle workspace topic subscribe/unsubscribe, presence tracking on connect/disconnect
- **Integration**: Register in WebSocket router alongside existing topic handlers
- **Verify**: Manual WebSocket test or integration test

#### 1.3 Agent Status Broadcasting
- **File**: Extend `WorkspaceService` or create `workspace_event_broadcaster.py`
- **Action**: When agent status changes (via Agent system events), broadcast `workspace.agent_status` event to workspace topic
- **Verify**: Status change triggers WS message

#### 1.4 Frontend: WebSocket Subscription Hook
- **File**: `web/src/hooks/useWorkspaceWebSocket.ts` (NEW)
- **Content**: Subscribe to `workspace:{id}` topic, dispatch events to store
- **Verify**: Browser console shows WS messages

#### 1.5 Frontend: Presence Bar Component
- **File**: `web/src/components/workspace/presence/PresenceBar.tsx` (NEW)
- **Content**: Show online users/agents as avatar row
- **Also**: `PresenceAvatar.tsx` (NEW)
- **Verify**: Visual check in browser

#### 1.6 Frontend: Workspace Store Extensions (Presence)
- **File**: `web/src/stores/workspace.ts` (EXTEND)
- **Action**: Add `onlineUsers`, `onlineAgents`, WS event handlers
- **Pattern**: useShallow for object selectors
- **Verify**: Store updates on WS events

#### 1.7 Frontend: Workspace Types Extensions
- **File**: `web/src/types/workspace.ts` (EXTEND)
- **Action**: Add `PresenceUser`, `PresenceAgent`, WS event type interfaces, extended WorkspaceAgent fields (hex_q, hex_r, theme_color, label, status)
- **Verify**: TypeScript compiles clean

### Phase 1 Verification
```bash
uv run pytest src/tests/ -k "workspace" -v
cd web && pnpm type-check && pnpm lint
```

### Phase 1 前端表现变化 (Frontend UI Changes)
- **WorkspaceDetail page**: New `PresenceBar` at top showing online users/agents as colored avatars with status dots (green=online, gray=offline)
- **Real-time updates**: When another user opens the workspace, their avatar appears instantly in the presence bar
- **Agent status**: Agent avatars show status indicator (idle=gray, busy=pulsing blue, error=red)

---

## Phase 2: Hex Topology Visualization (Frontend SVG)

**Goal**: Replace/enhance the existing TopologyBoard with an interactive hex grid that renders agents, corridors, human seats, and connections.

### Phase 2 Tasks

#### 2.1 useHexLayout Hook
- **File**: `web/src/components/workspace/hex/useHexLayout.ts` (NEW)
- **Content**: `hexToPixel`, `pixelToHex`, `generateGrid`, `hexDistance`, `getNeighbors`
- **Verify**: Unit test with vitest

#### 2.2 HexCell Component
- **File**: `web/src/components/workspace/hex/HexCell.tsx` (NEW)
- **Content**: SVG `<polygon>` for flat-top hex, click/hover handlers, selection highlight
- **Props**: `q, r, size, selected, occupied, onClick, onContextMenu`
- **Verify**: Renders correct polygon points

#### 2.3 HexAgent Component
- **File**: `web/src/components/workspace/hex/HexAgent.tsx` (NEW)
- **Content**: Agent avatar + label + status indicator overlaid on hex cell
- **Props**: Agent data (name, theme_color, status, label)
- **Verify**: Renders inside hex polygon

#### 2.4 HexCorridor Component
- **File**: `web/src/components/workspace/hex/HexCorridor.tsx` (NEW)
- **Content**: Corridor tile with dotted border or different fill
- **Verify**: Visually distinct from agent hexes

#### 2.5 HexHumanSeat Component
- **File**: `web/src/components/workspace/hex/HexHumanSeat.tsx` (NEW)
- **Content**: Human seat with user avatar or empty seat indicator
- **Verify**: Visually distinct

#### 2.6 HexFlowAnimation Component
- **File**: `web/src/components/workspace/hex/HexFlowAnimation.tsx` (NEW)
- **Content**: SVG animated path between connected hexes (dashed line with moving dots)
- **Uses**: SVG `<animate>` or CSS animation on `stroke-dashoffset`
- **Verify**: Animation renders smoothly

#### 2.7 HexTooltip Component
- **File**: `web/src/components/workspace/hex/HexTooltip.tsx` (NEW)
- **Content**: Popover on hex hover showing agent details / node info
- **Uses**: Ant Design Tooltip or custom positioned div
- **Verify**: Shows on hover, hides on leave

#### 2.8 HexGrid Container Component
- **File**: `web/src/components/workspace/hex/HexGrid.tsx` (NEW)
- **Content**: Main SVG container with:
  - Zoom (mouse wheel, 0.3-3.0 range)
  - Pan (mouse drag on empty space)
  - Grid background cells
  - Agent/corridor/seat/connection layers
  - Click-to-select, drag-to-move interactions
- **Verify**: Grid renders, zoom/pan works, agents display at correct hex positions

#### 2.9 Hex Grid API Integration
- **File**: `web/src/services/workspaceService.ts` (EXTEND)
- **Action**: Add `getAgentTopology()`, `moveAgentPosition()` API calls
- **Verify**: API calls succeed

#### 2.10 Workspace Store Extensions (Hex)
- **File**: `web/src/stores/workspace.ts` (EXTEND)
- **Action**: Add `hexAgents`, `hexNodes`, `hexEdges`, `selectedHex`, `moveAgent`, `fetchHexTopology`, WS topology event handler
- **Verify**: Store updates correctly on API and WS events

#### 2.11 Integrate HexGrid into WorkspaceDetail
- **File**: `web/src/pages/tenant/WorkspaceDetail.tsx` (MODIFY)
- **Action**: Replace or augment existing TopologyBoard with HexGrid as primary view
- **Layout**: Hex grid takes center area, sidebar for selected node details
- **Verify**: Page loads with hex grid, agents visible at positions

#### 2.12 Context Menu for Hex Cells
- **File**: `web/src/components/workspace/hex/HexContextMenu.tsx` (NEW)
- **Content**: Right-click menu with options: "Add Corridor", "Assign Task", "View Details", "Remove"
- **Uses**: Ant Design Dropdown or custom context menu
- **Verify**: Menu appears on right-click

### Phase 2 Verification
```bash
cd web && pnpm type-check && pnpm lint && pnpm build
# Visual verification in browser
```

### Phase 2 前端表现变化 (Frontend UI Changes)
- **WorkspaceDetail page completely transformed**: Center area now shows an interactive hex grid instead of the basic topology board
- **Hex grid**: Honeycomb pattern of hexagonal cells, empty cells shown as light outlines, occupied cells filled with agent avatars
- **Agent hexes**: Each agent shows as a colored hexagon (theme_color) with avatar, name label, and status dot
- **Corridor hexes**: Transparent/dotted hexagons connecting agent hexes, showing communication paths
- **Human seats**: Special hexagons with chair icon for human positions
- **Zoom/Pan**: Mouse wheel zooms in/out (0.3x to 3x), drag to pan the grid
- **Selection**: Click a hex to highlight it (blue border glow), sidebar shows details
- **Flow animation**: Animated dashed lines between connected hexes showing data flow direction
- **Context menu**: Right-click any hex for options (add corridor, assign task, etc.)
- **Hover tooltips**: Hover over any occupied hex shows agent details popover

---

## Phase 3: Blackboard + TaskBoard Enhancements

**Goal**: Upgrade Blackboard and TaskBoard with real-time WebSocket updates, agent task assignment, and priority-based sorting.

### Phase 3 Tasks

#### 3.1 TaskBoard Priority Sorting
- **File**: `web/src/components/workspace/TaskBoard.tsx` (MODIFY)
- **Action**: Add priority column, sort by priority, show estimated effort badges, blocker indicators
- **Verify**: Tasks sort correctly

#### 3.2 Task Agent Assignment UI
- **File**: `web/src/components/workspace/TaskBoard.tsx` (MODIFY)
- **Action**: Add agent assignment dropdown (select from workspace agents), show agent avatar on assigned tasks
- **Verify**: Assignment persists via API

#### 3.3 Blackboard Real-Time Updates
- **File**: `web/src/components/workspace/BlackboardPanel.tsx` (MODIFY)
- **Action**: Subscribe to `workspace.blackboard` WS events, auto-refresh on new posts/replies
- **Verify**: New post appears without page refresh

#### 3.4 Task Real-Time Updates
- **File**: `web/src/components/workspace/TaskBoard.tsx` (MODIFY)
- **Action**: Subscribe to `workspace.task` WS events, update task status/assignment in real-time
- **Verify**: Status change appears without page refresh

#### 3.5 Backend: Task/Blackboard WS Broadcasting
- **Files**: Extend task and blackboard API routers to broadcast WS events after mutations
- **Action**: After create/update/delete, publish to `workspace:{workspace_id}` topic
- **Verify**: WS message received on mutation

### Phase 3 Verification
```bash
cd web && pnpm type-check && pnpm lint
uv run pytest src/tests/ -k "task or blackboard" -v
```

### Phase 3 前端表现变化 (Frontend UI Changes)
- **TaskBoard**: New priority column with colored badges (P1=red, P2=orange, P3=yellow, P4=gray), effort size chips (S/M/L/XL), blocker icon with tooltip
- **Task assignment**: Dropdown to assign tasks to workspace agents, assigned agent shown as mini avatar on task card
- **Real-time tasks**: When another user changes a task status, the card moves instantly (no refresh)
- **Real-time blackboard**: New posts slide in from top with subtle animation, replies appear under parent post instantly
- **Completed tasks**: Show with strikethrough text and completion timestamp

---

## Phase 4: OKR System + Gene/Skill Packages

**Goal**: Implement the CyberObjective OKR hierarchy UI and Gene/Skill package registry.

### Phase 4 Tasks

#### 4.1 Frontend: ObjectiveList Component
- **File**: `web/src/components/workspace/objectives/ObjectiveList.tsx` (NEW)
- **Content**: Tree list showing Objectives with nested Key Results, progress bars, assignees
- **Verify**: Renders tree structure correctly

#### 4.2 Frontend: ObjectiveCard Component
- **File**: `web/src/components/workspace/objectives/ObjectiveCard.tsx` (NEW)
- **Content**: Card showing objective title, progress ring, assignee, due date, status badge
- **Verify**: Displays correctly

#### 4.3 Frontend: ObjectiveProgress Component
- **File**: `web/src/components/workspace/objectives/ObjectiveProgress.tsx` (NEW)
- **Content**: Circular progress ring (SVG) with percentage text
- **Verify**: Renders 0-100% correctly

#### 4.4 Frontend: ObjectiveCreateModal
- **File**: `web/src/components/workspace/objectives/ObjectiveCreateModal.tsx` (NEW)
- **Content**: Ant Design Modal form for creating/editing objectives and key results
- **Verify**: Creates objective via API

#### 4.5 Frontend: Objective Service + Store
- **File**: `web/src/services/workspaceService.ts` (EXTEND) + `web/src/stores/workspace.ts` (EXTEND)
- **Action**: Add objective CRUD API calls and store state
- **Verify**: CRUD operations work end-to-end

#### 4.6 Backend: CyberGene Domain Entity + Repository
- **Files**: `src/domain/model/workspace/cyber_gene.py` (NEW), `src/domain/ports/repositories/workspace/cyber_gene_repository.py` (NEW)
- **Verify**: ruff + pyright clean

#### 4.7 Backend: CyberGene ORM + SQL Repository
- **Files**: Extend ORM models, create `sql_cyber_gene_repository.py` (NEW)
- **Verify**: ruff + pyright clean

#### 4.8 Backend: Alembic Migration for Genes
- **Command**: `PYTHONPATH=. uv run alembic revision --autogenerate -m "cyber_office_phase4_genes"`
- **Verify**: Migration applies cleanly

#### 4.9 Backend: CyberGene API Router
- **File**: `src/infrastructure/adapters/primary/web/routers/cyber_genes.py` (NEW)
- **Endpoints**: CRUD + assign/unassign to agents
- **Verify**: API tests pass

#### 4.10 Frontend: Gene Components
- **Files**: `GeneList.tsx`, `GeneCard.tsx`, `GeneAssignModal.tsx` (all NEW in `web/src/components/workspace/genes/`)
- **Verify**: Gene list renders, assignment works

#### 4.11 HexObjective Component
- **File**: `web/src/components/workspace/hex/HexObjective.tsx` (NEW)
- **Content**: OKR node rendered on hex grid (target/flag icon with progress ring)
- **Verify**: Renders on hex grid at assigned position

#### 4.12 Integrate Objectives + Genes into WorkspaceDetail
- **File**: `web/src/pages/tenant/WorkspaceDetail.tsx` (MODIFY)
- **Action**: Add Objectives tab/panel and Genes tab/panel
- **Verify**: New tabs visible and functional

### Phase 4 Verification
```bash
uv run ruff check src/ && uv run pyright src/domain/model/workspace/
PYTHONPATH=. uv run alembic upgrade head
cd web && pnpm type-check && pnpm lint && pnpm build
```

### Phase 4 前端表现变化 (Frontend UI Changes)
- **New Objectives tab**: Tree view of Objectives with nested Key Results, each showing circular progress ring (green when >80%, yellow >50%, red <50%)
- **Objective cards**: Title + description + assignee avatar + due date badge + progress percentage
- **Create/edit modal**: Form with title, description, type selector (Objective/Key Result), parent selector, date picker, assignee dropdown
- **Hex grid OKR nodes**: Objectives appear as special hex cells with target icon and mini progress ring
- **New Genes tab**: Grid/list of Gene packages (skill/tool bundles) with version badges, tags, and "Assign to Agent" button
- **Gene assignment**: Click agent on hex grid -> sidebar shows assigned genes with add/remove buttons

---

## Phase 5: Security Layer + Channel Plugins + Advanced Features

**Goal**: Add enterprise-grade security evaluation, channel plugin framework, and advanced hex interactions. This is the EE (Enterprise Edition) phase.

### Phase 5 Tasks

#### 5.1 Security Evaluation Pipeline
- **File**: `src/infrastructure/security/workspace_security.py` (NEW)
- **Content**: Before/after evaluation hooks for workspace operations
- **Pattern**: Middleware-style pipeline (request -> evaluate -> allow/deny -> execute -> audit)
- **Verify**: Unit test with mocked evaluator

#### 5.2 Permission Matrix for Workspace Operations
- **File**: `src/domain/model/workspace/workspace_permissions.py` (NEW)
- **Content**: Fine-grained permission definitions per workspace role
- **Actions**: manage_agents, move_agents, manage_tasks, manage_objectives, manage_genes, manage_blackboard, manage_topology
- **Verify**: Permission checks enforced in API endpoints

#### 5.3 Channel Plugin Framework
- **File**: `src/infrastructure/plugins/workspace_channel.py` (NEW)
- **Content**: Abstract base for workspace communication channels (Slack, DingTalk, Feishu, etc.)
- **Integration**: Extends existing MemStack plugin system
- **Verify**: Base class importable, example plugin skeleton

#### 5.4 Advanced Hex Interactions
- **Frontend**: Drag-and-drop agent repositioning with snap-to-hex
- **Frontend**: Multi-select hex cells for bulk operations
- **Frontend**: Mini-map overlay for large hex grids
- **Verify**: Visual + functional testing in browser

#### 5.5 Workspace Activity Audit Log
- **File**: `src/infrastructure/adapters/secondary/persistence/sql_workspace_audit.py` (NEW)
- **Content**: Record all workspace mutations (who did what, when) for compliance
- **Verify**: Audit entries created on workspace operations

### Phase 5 Verification
```bash
make check  # Full format + lint + test
cd web && pnpm build
```

### Phase 5 前端表现变化 (Frontend UI Changes)
- **Drag-and-drop**: Agents can be dragged between hex cells with smooth snap-to-hex animation
- **Multi-select**: Shift+click to select multiple hexes, bulk operations menu appears
- **Mini-map**: Small overview map in corner for large grids, click to navigate
- **Permission indicators**: Locked icons on operations user doesn't have permission for
- **Audit trail**: New "Activity" tab showing timestamped log of all workspace changes

---

## Cross-Phase: Auto-Provisioning

### Auto-Create Workspace on Project Creation

- **Location**: Either in project creation endpoint or as a domain event handler
- **When**: Phase 0 (backend) + Phase 2 (frontend shows hex grid automatically)
- **Logic**: When `POST /projects` succeeds, create Workspace with default hex_layout_config
- **Verify**: Creating a project also creates a workspace

---

## Dependency Graph

```
Phase 0 (Foundation)
  └── Phase 1 (WebSocket) ──┐
       └── Phase 2 (Hex UI) ─┤
            └── Phase 3 (BB+Task) ──┐
                 └── Phase 4 (OKR+Gene) ──┐
                      └── Phase 5 (Security+Channels)
```

Each phase depends on the previous. No parallel phase execution.

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Migration breaks existing data | Review autogenerated migration carefully; add column defaults; test with existing data |
| SVG hex grid performance with many nodes | Virtualize: only render hexes in viewport; use `requestAnimationFrame` for animations |
| WebSocket message storm | Throttle/debounce broadcasts; batch topology updates |
| Hex coordinate collisions | DB unique constraint enforces one-entity-per-hex; API validates before move |
| Breaking existing workspace UI | Extend, don't replace; feature-flag new hex view; keep legacy topology board as fallback |

---

## Success Criteria

- [ ] All 6 phases implemented and verified
- [ ] Alembic migrations apply cleanly on fresh and existing databases
- [ ] Backend: ruff + pyright clean on all modified files
- [ ] Frontend: pnpm type-check + lint + build all pass
- [ ] Hex grid renders correctly with 20+ agents
- [ ] WebSocket presence updates within 500ms
- [ ] OKR tree CRUD works end-to-end
- [ ] No regressions in existing workspace features
