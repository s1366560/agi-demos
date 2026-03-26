# CyberOffice Architecture Document

> Status: APPROVED | Version: 1.0 | Date: 2026-03-25

## 1. Overview

CyberOffice (赛博办公室) extends MemStack's existing Workspace infrastructure to create a hex-topology-based collaborative environment where human users and AI agents coexist as first-class participants. The system introduces hexagonal spatial layout, real-time presence, OKR-driven objectives, and a gene/skill package registry.

### Architecture Decisions (Locked)

| ID | Decision | Rationale |
|----|----------|-----------|
| A1 | CyberOffice 1:1 with Project | Each Project automatically gets one CyberOffice (Workspace). Simplifies tenant isolation and avoids orphan workspaces |
| A2 | Agent identity = lightweight wrapper | CyberAgent wraps existing `Conversation` + metadata (hex position, role, status, theme_color). No new agent runtime |
| A3 | Hex rendering = Custom React SVG | Lightweight, controllable, integrates with Ant Design. No Three.js/D3 dependency |
| A4 | Scope = Phase 0-5 FULL | Complete implementation across all 6 phases |

### Extension Strategy

**Extend, don't rebuild.** MemStack already has 9 workspace domain entities, 6 repository interfaces, 7 SQL implementations, 5 API routers, and a complete frontend stack. CyberOffice adds fields to existing entities and introduces 2-3 new entities.

---

## 2. Domain Model Extensions

### 2.1 Existing Entities to Extend

#### WorkspaceAgent (add hex positioning + visual identity)

```python
# EXISTING fields (keep all)
workspace_id: str
agent_id: str
display_name: str | None
description: str | None
config: dict[str, Any]
is_active: bool
created_at: datetime
updated_at: datetime | None

# NEW fields
hex_q: int = 0           # Axial hex coordinate Q
hex_r: int = 0           # Axial hex coordinate R
label: str | None = None  # Short role label (e.g., "Coder", "Reviewer")
theme_color: str | None = None  # Hex color string e.g. "#ff6b35"
status: str = "idle"      # idle | busy | error | offline
```

#### TopologyNode (add hex coordinates + extended types)

```python
# EXISTING fields (keep all)
workspace_id: str
node_type: TopologyNodeType  # EXTEND enum
ref_id: str | None
title: str
position_x: float  # Keep for backward compat
position_y: float  # Keep for backward compat
data: dict[str, Any]

# NEW fields
hex_q: int | None = None   # Axial hex coordinate Q (None = legacy node)
hex_r: int | None = None   # Axial hex coordinate R (None = legacy node)
status: str = "active"     # active | archived | locked
tags: list[str] = field(default_factory=list)
```

**TopologyNodeType enum extension:**
```python
class TopologyNodeType(str, Enum):
    USER = "user"
    AGENT = "agent"
    TASK = "task"
    NOTE = "note"
    # NEW types
    CORRIDOR = "corridor"     # Passthrough hex tile
    HUMAN_SEAT = "human_seat" # Designated human position
    OBJECTIVE = "objective"   # OKR node on hex grid
```

#### TopologyEdge (add hex pair coordinates)

```python
# EXISTING fields (keep all)
workspace_id: str
source_node_id: str
target_node_id: str
label: str | None
data: dict[str, Any]

# NEW fields
source_hex_q: int | None = None
source_hex_r: int | None = None
target_hex_q: int | None = None
target_hex_r: int | None = None
direction: str | None = None    # "e", "w", "ne", "nw", "se", "sw"
auto_created: bool = False       # True if system-generated adjacency edge
```

#### WorkspaceTask (add priority + agent assignment fields)

```python
# EXISTING fields (keep all)
workspace_id: str
title: str
description: str | None
created_by: str
assignee_user_id: str | None
assignee_agent_id: str | None
status: WorkspaceTaskStatus
metadata: dict[str, Any]

# NEW fields
priority: int = 0               # 0=none, 1=low, 2=medium, 3=high, 4=urgent
estimated_effort: str | None = None  # "S", "M", "L", "XL"
blocker_reason: str | None = None
completed_at: datetime | None = None
archived_at: datetime | None = None
```

#### Workspace (add office configuration)

```python
# EXISTING fields (keep all)
tenant_id: str
project_id: str
name: str
created_by: str
description: str | None
is_archived: bool
metadata: dict[str, Any]
created_at: datetime
updated_at: datetime | None

# NEW fields
office_status: str = "active"   # active | archived | maintenance
hex_layout_config: dict[str, Any] = field(default_factory=dict)
# hex_layout_config schema:
# {
#   "hex_size": 60,           # pixel radius of each hex
#   "origin_q": 0,            # center hex Q
#   "origin_r": 0,            # center hex R
#   "grid_radius": 5,         # visible hex ring count from center
#   "show_coordinates": false  # debug overlay
# }
```

### 2.2 New Entities

#### CyberObjective (OKR hierarchy)

```python
@dataclass(kw_only=True)
class CyberObjectiveType(str, Enum):
    OBJECTIVE = "objective"
    KEY_RESULT = "key_result"

@dataclass(kw_only=True)
class CyberObjective(Entity):
    """OKR node: Objective contains Key Results."""
    workspace_id: str
    title: str
    description: str | None = None
    obj_type: CyberObjectiveType = CyberObjectiveType.OBJECTIVE
    parent_id: str | None = None   # Objective ID for key_results
    progress: float = 0.0          # 0.0 - 1.0
    created_by: str = ""
    assignee_agent_id: str | None = None
    assignee_user_id: str | None = None
    status: str = "active"         # active | completed | cancelled
    due_date: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
```

#### CyberGene (Skill/Tool package registry) -- Phase 4

```python
@dataclass(kw_only=True)
class CyberGeneType(str, Enum):
    SKILL = "skill"
    MCP_TOOL = "mcp_tool"
    COMPOSITE = "composite"

@dataclass(kw_only=True)
class CyberGene(Entity):
    """Packaged capability that can be assigned to agents."""
    workspace_id: str
    name: str
    gene_type: CyberGeneType
    ref_id: str | None = None      # skill_id or mcp_tool_id
    description: str | None = None
    version: str = "1.0.0"
    config: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    is_active: bool = True
    created_by: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
```

### 2.3 Hex Coordinate System

Uses **axial coordinates (q, r)** following the cube coordinate convention where `s = -q - r`.

```
Adjacent offsets (6 neighbors):
ADJACENT_OFFSETS = [(1,0), (-1,0), (0,1), (0,-1), (1,-1), (-1,1)]

Pixel conversion (flat-top hex):
  x = hex_size * (3/2 * q)
  y = hex_size * (sqrt(3)/2 * q + sqrt(3) * r)

Distance:
  hex_distance(a, b) = max(|aq-bq|, |ar-br|, |aq+ar-bq-br|)
```

**Domain utility functions** (placed in `src/domain/model/workspace/hex_utils.py`):

```python
ADJACENT_OFFSETS: list[tuple[int, int]] = [(1,0), (-1,0), (0,1), (0,-1), (1,-1), (-1,1)]

def is_adjacent(q1: int, r1: int, q2: int, r2: int) -> bool:
    return (q2 - q1, r2 - r1) in ADJACENT_OFFSETS

def hex_distance(q1: int, r1: int, q2: int, r2: int) -> int:
    dq, dr = q2 - q1, r2 - r1
    return max(abs(dq), abs(dr), abs(dq + dr))

def hex_neighbors(q: int, r: int) -> list[tuple[int, int]]:
    return [(q + dq, r + dr) for dq, dr in ADJACENT_OFFSETS]

def hex_to_pixel(q: int, r: int, size: float = 60.0) -> tuple[float, float]:
    x = size * 1.5 * q
    y = size * (0.8660254037844386 * q + 1.7320508075688772 * r)
    return (x, y)

def pixel_to_hex(x: float, y: float, size: float = 60.0) -> tuple[int, int]:
    q = (2.0/3.0 * x) / size
    r = (-1.0/3.0 * x + (3**0.5)/3.0 * y) / size
    return _axial_round(q, r)

def _axial_round(q: float, r: float) -> tuple[int, int]:
    s = -q - r
    rq, rr, rs = round(q), round(r), round(s)
    dq, dr, ds = abs(rq - q), abs(rr - r), abs(rs - s)
    if dq > dr and dq > ds:
        rq = -rr - rs
    elif dr > ds:
        rr = -rq - rs
    return (int(rq), int(rr))
```

---

## 3. Repository & Persistence Layer

### 3.1 New Repository Interfaces

```python
# src/domain/ports/repositories/workspace/cyber_objective_repository.py
class CyberObjectiveRepository(ABC):
    async def save(self, objective: CyberObjective) -> CyberObjective: ...
    async def find_by_id(self, objective_id: str) -> CyberObjective | None: ...
    async def find_by_workspace(self, workspace_id: str) -> list[CyberObjective]: ...
    async def find_children(self, parent_id: str) -> list[CyberObjective]: ...
    async def update(self, objective: CyberObjective) -> CyberObjective: ...
    async def delete(self, objective_id: str) -> None: ...

# src/domain/ports/repositories/workspace/cyber_gene_repository.py (Phase 4)
class CyberGeneRepository(ABC):
    async def save(self, gene: CyberGene) -> CyberGene: ...
    async def find_by_id(self, gene_id: str) -> CyberGene | None: ...
    async def find_by_workspace(self, workspace_id: str) -> list[CyberGene]: ...
    async def find_by_agent(self, workspace_id: str, agent_id: str) -> list[CyberGene]: ...
    async def delete(self, gene_id: str) -> None: ...
```

### 3.2 ORM Model Extensions

All extensions use **Alembic migrations** -- never direct DB modifications.

**New ORM models:**
- `CyberObjectiveModel` in `sql_cyber_objective_repository.py`
- `CyberGeneModel` in `sql_cyber_gene_repository.py` (Phase 4)

**Extended columns** (added via Alembic `op.add_column`):
- `workspace_agents` table: `hex_q`, `hex_r`, `label`, `theme_color`, `status`
- `topology_nodes` table: `hex_q`, `hex_r`, `status`, `tags` (JSON)
- `topology_edges` table: `source_hex_q`, `source_hex_r`, `target_hex_q`, `target_hex_r`, `direction`, `auto_created`
- `workspace_tasks` table: `priority`, `estimated_effort`, `blocker_reason`, `completed_at`, `archived_at`
- `workspaces` table: `office_status`, `hex_layout_config` (JSON)

**New tables:**
- `cyber_objectives`: workspace_id (FK), title, description, obj_type, parent_id (self-FK), progress, created_by, assignee_agent_id, assignee_user_id, status, due_date, metadata (JSON), created_at, updated_at
- `cyber_genes` (Phase 4): workspace_id (FK), name, gene_type, ref_id, description, version, config (JSON), tags (JSON), is_active, created_by, created_at, updated_at

**Unique constraints:**
- `workspace_agents`: UNIQUE(workspace_id, hex_q, hex_r) -- one agent per hex cell
- `topology_nodes`: UNIQUE(workspace_id, hex_q, hex_r) WHERE hex_q IS NOT NULL -- one node per hex cell
- `cyber_objectives`: INDEX(workspace_id, parent_id)

---

## 4. API Layer

### 4.1 Extended Endpoints

All endpoints are under `/api/v1/workspaces/{workspace_id}/...` (existing router pattern).

**WorkspaceAgent hex positioning (extend existing router):**
```
PATCH  /agents/{agent_id}/position    # Move agent to hex cell
  Body: { "hex_q": int, "hex_r": int }
  Response: WorkspaceAgent (updated)
  Validation: Target cell must be empty or a corridor

GET    /agents/topology               # Get all agents with hex positions
  Response: { agents: WorkspaceAgent[], connections: TopologyEdge[] }
```

**CyberObjective CRUD (new router):**
```
POST   /objectives                    # Create objective or key_result
GET    /objectives                    # List all objectives (flat or tree)
GET    /objectives/{id}               # Get single objective with children
PATCH  /objectives/{id}               # Update objective
DELETE /objectives/{id}               # Delete objective (cascades KRs)
PATCH  /objectives/{id}/progress      # Update progress (0.0-1.0)
```

**CyberGene CRUD (Phase 4, new router):**
```
POST   /genes                         # Register gene package
GET    /genes                         # List workspace genes
GET    /genes/{id}                    # Get gene detail
PATCH  /genes/{id}                    # Update gene
DELETE /genes/{id}                    # Delete gene
POST   /agents/{agent_id}/genes       # Assign gene to agent
DELETE /agents/{agent_id}/genes/{id}  # Remove gene from agent
```

### 4.2 Schema DTOs

New Pydantic schemas in `src/application/schemas/`:

```python
# workspace_cyber_schemas.py

class AgentPositionRequest(BaseModel):
    hex_q: int
    hex_r: int

class CyberObjectiveCreate(BaseModel):
    title: str
    description: str | None = None
    obj_type: str = "objective"  # "objective" | "key_result"
    parent_id: str | None = None
    assignee_agent_id: str | None = None
    assignee_user_id: str | None = None
    due_date: datetime | None = None

class CyberObjectiveUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    progress: float | None = None
    status: str | None = None
    due_date: datetime | None = None

class CyberObjectiveResponse(BaseModel):
    id: str
    workspace_id: str
    title: str
    description: str | None
    obj_type: str
    parent_id: str | None
    progress: float
    status: str
    created_by: str
    assignee_agent_id: str | None
    assignee_user_id: str | None
    due_date: datetime | None
    children: list["CyberObjectiveResponse"] = []
    created_at: datetime
    updated_at: datetime | None
```

---

## 5. WebSocket Real-Time Layer

### 5.1 Topic Structure

Leverages existing `TopicType.WORKSPACE` and `TopicManager`:

```
Topic format: workspace:{workspace_id}

Sub-channels (via event type field):
- workspace.presence    # User/agent join/leave
- workspace.agent_status  # Agent idle/busy/error transitions
- workspace.topology    # Hex grid changes (node add/move/remove)
- workspace.task        # Task status changes
- workspace.blackboard  # New posts/replies
- workspace.objective   # OKR progress updates
```

### 5.2 Event Payloads

```json
// Presence event
{
  "type": "workspace.presence",
  "action": "join" | "leave",
  "data": {
    "user_id": "...",
    "display_name": "...",
    "timestamp": "..."
  }
}

// Agent status event
{
  "type": "workspace.agent_status",
  "data": {
    "agent_id": "...",
    "status": "busy",
    "current_task": "Analyzing code...",
    "hex_q": 2,
    "hex_r": -1
  }
}

// Topology change event
{
  "type": "workspace.topology",
  "action": "move" | "add" | "remove",
  "data": {
    "node_id": "...",
    "node_type": "agent",
    "from_hex": [1, 0],
    "to_hex": [2, -1]
  }
}
```

### 5.3 Presence Tracking

```python
# src/application/services/workspace_presence_service.py

class WorkspacePresenceService:
    """Tracks who is online in each workspace."""

    def __init__(self, redis_client: Redis, topic_manager: TopicManager):
        self._redis = redis_client
        self._topics = topic_manager

    async def join(self, workspace_id: str, user_id: str, display_name: str) -> None:
        key = f"workspace:presence:{workspace_id}"
        await self._redis.hset(key, user_id, json.dumps({
            "display_name": display_name,
            "joined_at": datetime.now(UTC).isoformat(),
        }))
        await self._redis.expire(key, 86400)  # 24h TTL
        await self._broadcast_presence(workspace_id, "join", user_id, display_name)

    async def leave(self, workspace_id: str, user_id: str) -> None:
        key = f"workspace:presence:{workspace_id}"
        await self._redis.hdel(key, user_id)
        await self._broadcast_presence(workspace_id, "leave", user_id, "")

    async def get_online_users(self, workspace_id: str) -> list[dict[str, Any]]:
        key = f"workspace:presence:{workspace_id}"
        members = await self._redis.hgetall(key)
        return [{"user_id": uid, **json.loads(data)} for uid, data in members.items()]

    async def _broadcast_presence(
        self, workspace_id: str, action: str, user_id: str, display_name: str
    ) -> None:
        await self._topics.broadcast(
            f"workspace:{workspace_id}",
            {
                "type": "workspace.presence",
                "action": action,
                "data": {"user_id": user_id, "display_name": display_name},
            },
        )
```

---

## 6. Frontend Architecture

### 6.1 Component Tree

```
web/src/
├── components/workspace/
│   ├── hex/                          # NEW: Hex grid components
│   │   ├── HexGrid.tsx              # SVG hex grid container with zoom/pan
│   │   ├── HexCell.tsx              # Single hex cell renderer
│   │   ├── HexAgent.tsx             # Agent avatar on hex cell
│   │   ├── HexCorridor.tsx          # Corridor path between cells
│   │   ├── HexHumanSeat.tsx         # Human seat indicator
│   │   ├── HexObjective.tsx         # OKR node on grid
│   │   ├── HexFlowAnimation.tsx     # Animated data flow between nodes
│   │   ├── HexTooltip.tsx           # Hover tooltip for hex cells
│   │   └── useHexLayout.ts          # Hook: axial coord <-> pixel conversion
│   ├── objectives/                   # NEW: OKR components
│   │   ├── ObjectiveList.tsx        # Tree list of objectives + KRs
│   │   ├── ObjectiveCard.tsx        # Single objective card
│   │   ├── ObjectiveProgress.tsx    # Progress bar/ring
│   │   └── ObjectiveCreateModal.tsx # Create/edit objective modal
│   ├── genes/                        # NEW (Phase 4): Gene components
│   │   ├── GeneList.tsx             # Gene package list
│   │   ├── GeneCard.tsx             # Gene card with assign button
│   │   └── GeneAssignModal.tsx      # Assign gene to agent
│   ├── presence/                     # NEW: Presence components
│   │   ├── PresenceBar.tsx          # Online users/agents bar
│   │   └── PresenceAvatar.tsx       # User/agent online indicator
│   ├── BlackboardPanel.tsx          # EXISTING (extend)
│   ├── TaskBoard.tsx                # EXISTING (extend)
│   ├── TopologyBoard.tsx            # EXISTING (replace internals with hex)
│   └── MemberPanel.tsx              # EXISTING (extend)
├── pages/tenant/
│   ├── WorkspaceList.tsx            # EXISTING (minor updates)
│   └── WorkspaceDetail.tsx          # EXISTING (major refactor: add hex view)
├── stores/
│   └── workspace.ts                 # EXISTING (extend with hex + presence state)
├── services/
│   └── workspaceService.ts          # EXISTING (extend with new endpoints)
└── types/
    └── workspace.ts                 # EXISTING (extend with new interfaces)
```

### 6.2 HexGrid SVG Architecture

The hex grid uses a `<svg>` with `<g>` transform groups for zoom/pan:

```tsx
<svg viewBox="..." width="100%" height="100%">
  {/* Background grid layer */}
  <g className="hex-grid-layer" transform={`translate(${panX},${panY}) scale(${zoom})`}>
    {/* Empty hex cells (grid background) */}
    {gridCells.map(cell => <HexCell key={`${cell.q},${cell.r}`} {...cell} />)}

    {/* Corridor paths */}
    {corridors.map(c => <HexCorridor key={c.id} {...c} />)}

    {/* Edge connections with flow animation */}
    {edges.map(e => <HexFlowAnimation key={e.id} {...e} />)}

    {/* Agent nodes */}
    {agents.map(a => <HexAgent key={a.id} {...a} />)}

    {/* Human seats */}
    {humanSeats.map(h => <HexHumanSeat key={h.id} {...h} />)}

    {/* Objective nodes */}
    {objectives.map(o => <HexObjective key={o.id} {...o} />)}
  </g>
</svg>
```

**Interaction model:**
- Mouse wheel → zoom (0.3 to 3.0)
- Mouse drag on empty space → pan
- Click hex cell → select (shows detail sidebar)
- Drag agent → move to new hex (PATCH position API)
- Right-click hex → context menu (add corridor, assign task, etc.)

### 6.3 useHexLayout Hook

```typescript
// web/src/components/workspace/hex/useHexLayout.ts

interface HexLayoutConfig {
  hexSize: number;     // default 60
  originQ: number;     // default 0
  originR: number;     // default 0
  gridRadius: number;  // default 5
}

interface HexCoord { q: number; r: number; }
interface PixelCoord { x: number; y: number; }

export function useHexLayout(config: HexLayoutConfig) {
  const hexToPixel = (q: number, r: number): PixelCoord => ({
    x: config.hexSize * 1.5 * q,
    y: config.hexSize * (Math.sqrt(3) / 2 * q + Math.sqrt(3) * r),
  });

  const pixelToHex = (x: number, y: number): HexCoord => {
    const q = (2/3 * x) / config.hexSize;
    const r = (-1/3 * x + Math.sqrt(3)/3 * y) / config.hexSize;
    return axialRound(q, r);
  };

  const generateGrid = (radius: number): HexCoord[] => {
    const cells: HexCoord[] = [];
    for (let q = -radius; q <= radius; q++) {
      for (let r = Math.max(-radius, -q-radius); r <= Math.min(radius, -q+radius); r++) {
        cells.push({ q, r });
      }
    }
    return cells;
  };

  const hexDistance = (a: HexCoord, b: HexCoord): number => {
    const dq = b.q - a.q;
    const dr = b.r - a.r;
    return Math.max(Math.abs(dq), Math.abs(dr), Math.abs(dq + dr));
  };

  const getNeighbors = (q: number, r: number): HexCoord[] => {
    return [[1,0],[-1,0],[0,1],[0,-1],[1,-1],[-1,1]]
      .map(([dq, dr]) => ({ q: q+dq, r: r+dr }));
  };

  return { hexToPixel, pixelToHex, generateGrid, hexDistance, getNeighbors };
}
```

### 6.4 State Management Extensions

```typescript
// Extend web/src/stores/workspace.ts

interface WorkspaceState {
  // ... existing state ...

  // NEW: Hex topology
  hexAgents: WorkspaceAgent[];       // Agents with hex positions
  hexNodes: TopologyNode[];          // All hex-positioned nodes
  hexEdges: TopologyEdge[];          // Hex connections
  selectedHex: { q: number; r: number } | null;

  // NEW: Presence
  onlineUsers: PresenceUser[];
  onlineAgents: PresenceAgent[];

  // NEW: Objectives
  objectives: CyberObjective[];

  // NEW: Actions
  moveAgent: (agentId: string, hexQ: number, hexR: number) => Promise<void>;
  fetchHexTopology: (workspaceId: string) => Promise<void>;
  selectHex: (q: number, r: number) => void;
  subscribeWorkspaceWS: (workspaceId: string) => void;
  unsubscribeWorkspaceWS: () => void;

  // NEW: Objective actions
  fetchObjectives: (workspaceId: string) => Promise<void>;
  createObjective: (data: CyberObjectiveCreate) => Promise<void>;
  updateObjectiveProgress: (id: string, progress: number) => Promise<void>;
}
```

### 6.5 WebSocket Integration (Frontend)

The frontend subscribes to workspace topics via the existing WebSocket connection:

```typescript
// In workspace store or dedicated hook
const subscribeWorkspaceWS = (workspaceId: string) => {
  const ws = getWebSocketConnection();  // Existing WS singleton

  // Subscribe to workspace topic
  ws.send(JSON.stringify({
    type: "subscribe",
    topic: `workspace:${workspaceId}`,
  }));

  // Handle incoming events
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    switch (msg.type) {
      case "workspace.presence":
        handlePresenceUpdate(msg);
        break;
      case "workspace.agent_status":
        handleAgentStatusUpdate(msg);
        break;
      case "workspace.topology":
        handleTopologyUpdate(msg);
        break;
      case "workspace.task":
        handleTaskUpdate(msg);
        break;
      case "workspace.objective":
        handleObjectiveUpdate(msg);
        break;
    }
  };
};
```

---

## 7. Auto-Provisioning: Project -> Workspace

When a Project is created, a Workspace is auto-provisioned (A1 decision):

```python
# In WorkspaceService or as a domain event handler

async def auto_provision_workspace(
    project: Project,
    user_id: str,
    workspace_repo: WorkspaceRepository,
    member_repo: WorkspaceMemberRepository,
) -> Workspace:
    """Create default CyberOffice workspace for a new project."""
    workspace = Workspace(
        tenant_id=project.tenant_id,
        project_id=project.id,
        name=f"{project.name} Office",
        created_by=user_id,
        description=f"CyberOffice for project: {project.name}",
        office_status="active",
        hex_layout_config={
            "hex_size": 60,
            "origin_q": 0,
            "origin_r": 0,
            "grid_radius": 5,
            "show_coordinates": False,
        },
    )
    await workspace_repo.save(workspace)

    # Add creator as owner
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user_id,
        role=WorkspaceRole.OWNER,
    )
    await member_repo.save(member)

    return workspace
```

---

## 8. CE/EE Boundary

Following nodeskclaw convention:

| Feature | Edition | Phase |
|---------|---------|-------|
| Hex grid visualization | CE | 0-2 |
| Agent hex positioning | CE | 0 |
| Corridor/connection system | CE | 2 |
| Blackboard (basic) | CE | 0 (existing) |
| Task board with priority | CE | 3 |
| OKR objectives | CE | 4 |
| WebSocket presence | CE | 1 |
| Gene/Skill packages | CE | 4 |
| Security eval layer | EE | 5 |
| Channel plugin framework | EE | 5 |
| Advanced permission matrix | EE | 5 |
| Cross-workspace federation | EE | Future |

---

## 9. Database Migration Strategy

Single migration file per phase, using `op.add_column` for extensions and `op.create_table` for new entities.

**Phase 0 migration covers:**
1. Add columns to `workspace_agents` (hex_q, hex_r, label, theme_color, status)
2. Add columns to `topology_nodes` (hex_q, hex_r, status, tags)
3. Add columns to `topology_edges` (source/target hex coords, direction, auto_created)
4. Add columns to `workspace_tasks` (priority, estimated_effort, blocker_reason, completed_at, archived_at)
5. Add columns to `workspaces` (office_status, hex_layout_config)
6. Create `cyber_objectives` table
7. Add unique constraints for hex positioning

**Phase 4 migration covers:**
1. Create `cyber_genes` table
2. Create `agent_gene_assignments` junction table (workspace_agent_id, gene_id)

---

## 10. Technology Choices Summary

| Concern | Choice | Rationale |
|---------|--------|-----------|
| Hex rendering | React SVG (custom) | Lightweight, Ant Design compatible, no extra deps |
| Coordinate system | Axial (q, r) | Standard for hex grids, simple neighbor calculation |
| Real-time | WebSocket via TopicManager | Already exists, WORKSPACE topic type ready |
| Presence | Redis hash + WS broadcast | Fast, ephemeral, scales horizontally |
| State management | Zustand (extend existing store) | Already in use, minimal API |
| ORM | SQLAlchemy (extend models) | Already in use, Alembic for migrations |
| API | FastAPI (extend routers) | Already in use, OpenAPI auto-docs |
