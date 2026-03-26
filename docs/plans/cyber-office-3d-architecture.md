# Cyber Office 3D Architecture Plan

## Overview

Enhance the existing R3F-based 3D workspace view with:
1. **Message Flow Particles** - Animated particles traveling between agents during collaboration
2. **Enhanced Avatars** - Grabby-inspired robot avatars with status-driven animations
3. **Chat-to-3D Integration** - WebSocket events trigger 3D visual effects
4. **Robust Picking** - Improved raycasting with overlap resolution
5. **Visual Polish** - Hover/selection animations, camera focus, fog, and scene atmosphere

## Current State

### Existing R3F Components (`web/src/components/workspace/hex3d/`)

| File | What It Does | Status |
|------|--------------|--------|
| `HexCanvas3D.tsx` | Top-level Canvas + CameraAnimator + scene composition | Working |
| `HexScene.tsx` | Ambient/directional lights + ground plane | Minimal |
| `HexInstances.tsx` | Instanced hex tiles with three-mesh-bvh raycast | Working |
| `AgentMesh.tsx` | Simple cylinder+sphere agent with billboard label | Placeholder |
| `CorridorMesh.tsx` | Line-based corridor edges between hexes | Working |
| `useHex3DPick.ts` | Basic click/hover state management | Minimal |
| `index.ts` | Barrel export | Working |

### Dependencies Already Installed
- `three@0.183.2`
- `@react-three/fiber@9.5.0`
- `@react-three/drei@10.7.7`
- `three-mesh-bvh@0.9.9`

### Integration Point
`WorkspaceDetail.tsx` (line 89) subscribes to `unifiedEventService.subscribeWorkspace()` and dispatches `workspace_message_created` events. Currently only feeds ChatPanel, not the 3D view.

---

## Architecture Design

### Component Tree (Target)

```
WorkspaceDetail.tsx
  +-- HexCanvas3D (ref: HexCanvas3DRef)
       +-- HexScene (lights, fog, ground)
       +-- HexInstances (instanced hex tiles + BVH raycast)
       +-- AgentMesh[] (enhanced avatars per agent)
       |    +-- GrabbyAvatar (robot body, head, arms, status ring)
       |    +-- AgentLabel (Billboard + Text)
       |    +-- ThoughtBubble (transient overlay during "thinking")
       +-- CorridorMesh[] (corridor edges)
       +-- MessageFlowManager (particle system for collaboration flows)
       |    +-- FlowParticle[] (animated spheres along hex paths)
       +-- CameraAnimator (OrbitControls + lerp focus)
```

### New Files to Create

| File | Purpose |
|------|---------|
| `MessageFlowManager.tsx` | R3F component managing active flow particles |
| `FlowParticle.tsx` | Single animated particle traveling a hex path |
| `GrabbyAvatar.tsx` | Detailed robot avatar with status animations |
| `ThoughtBubble.tsx` | Transient thought/speech bubble overlay |
| `useMessageFlow.ts` | Hook: imperative API to trigger flows + state |
| `useAgentAnimation.ts` | Hook: per-agent status animation logic |
| `constants.ts` | Shared colors, geometries, materials |

### Files to Modify

| File | Changes |
|------|---------|
| `HexCanvas3D.tsx` | Add MessageFlowManager, expose `triggerMessageFlow` via ref, accept `onAgentEvent` |
| `HexScene.tsx` | Add fog, hemisphere light, improve ground material |
| `AgentMesh.tsx` | Swap simple cylinder for GrabbyAvatar component |
| `useHex3DPick.ts` | Add `pickBestHex` overlap resolution (project to camera NDC) |
| `WorkspaceDetail.tsx` | Wire workspace events to 3D triggers (flow particles, agent status) |

---

## Phase 1: Message Flow Particles

### Goal
When agent A sends a message mentioning agent B, animate a glowing particle traveling from A's hex to B's hex along the topology path.

### Design

#### `useMessageFlow.ts`
```typescript
interface FlowState {
  id: string;
  path: Vector3[];       // world-space waypoints
  progress: number;      // 0..1
  color: string;
  startTime: number;
}

interface UseMessageFlowReturn {
  flows: FlowState[];
  triggerFlow: (sourceAgentId: string, targetAgentId: string) => void;
}
```

- Uses BFS on topology edges to find shortest hex path between source and target
- Converts hex path to world-space Vector3[] waypoints
- Each flow has a TTL (3 seconds default), removed after completion
- Max 20 concurrent flows

#### `MessageFlowManager.tsx`
- R3F group component rendered inside HexCanvas3D
- Uses `useFrame` to advance all active flows each frame
- Each flow renders a small emissive sphere (shared geometry) that lerps along the path
- Trail effect: 3-4 trailing spheres with decreasing opacity
- On arrival at target: brief "burst" effect (scale up + fade)

#### `FlowParticle.tsx`
- Single flow: sphere mesh + optional trail meshes
- Uses `useFrame` for position interpolation along path
- Emissive material matching agent's theme color
- Self-removes when progress >= 1.0

### Integration in WorkspaceDetail.tsx

```typescript
// In the workspace event subscription (line 89-96):
if (type === 'workspace_message_created') {
  store.handleChatEvent({ type, data });
  
  // Trigger 3D flow if message has mentions and is from an agent
  const msg = data.message;
  if (msg.sender_type === 'agent' && msg.mentions?.length > 0) {
    hexCanvas3DRef.current?.triggerMessageFlow(msg.sender_id, msg.mentions);
  }
}

// Also handle agent:collaboration events when we add them
if (type === 'agent:collaboration') {
  hexCanvas3DRef.current?.triggerMessageFlow(data.instance_id, data.target);
}
```

### HexCanvas3D Ref Enhancement

```typescript
export interface HexCanvas3DRef {
  zoomToAgent: (agentId: string) => void;
  triggerMessageFlow: (sourceAgentId: string, targetAgentIds: string[]) => void;
  setAgentStatus: (agentId: string, status: string) => void;
}
```

---

## Phase 2: Enhanced Avatars (Grabby-Inspired)

### Goal
Replace the simple cylinder+sphere agent representation with a detailed robot avatar that animates based on agent status.

### Design

#### Status-to-Animation Mapping

| Agent Status | Animation State | Visual |
|-------------|----------------|--------|
| `idle` | Gentle bob | Slow vertical oscillation, dim emissive |
| `running` / `active` | Working | Arm movement, bright status ring, chest glow |
| `thinking` | Pondering | Head tilt, thought bubbles appear |
| `error` / `failed` | Alert | Red pulse on status ring, slight shake |
| `disconnected` | Gray | Desaturated colors, no glow |

#### `GrabbyAvatar.tsx`

Ported from DeskClaw's Grabby.ts but adapted for R3F declarative style:

```
GrabbyAvatar
  +-- group (main transform)
       +-- HeadGroup
       |    +-- Box (head)
       |    +-- Plane (screen face)
       |    +-- Circle (eyes) x2
       |    +-- Line (mouth)
       |    +-- Cylinder (antenna rod)
       |    +-- Sphere (antenna tip - glowing)
       +-- TorsoGroup
       |    +-- Box (body)
       |    +-- Plane (chest panel)
       |    +-- Circle (chest light - glowing)
       +-- LeftArm + RightArm
       |    +-- Sphere (shoulder)
       |    +-- Cylinder (arm segment)
       |    +-- Sphere (hand)
       +-- StatusRing (ring geometry, color = status)
       +-- HoverRing (ring geometry, visible on hover)
```

Shared geometries/materials created once in `constants.ts` and reused across all avatars.

#### `useAgentAnimation.ts`

```typescript
function useAgentAnimation(status: string, isHovered: boolean, isSelected: boolean) {
  // Returns per-frame animation values:
  // - headTilt, armSwing, bobOffset
  // - emissiveIntensity, statusRingColor
  // - thoughtBubbleOpacity
  // Uses useFrame internally
}
```

#### `ThoughtBubble.tsx`
- 3 circles (small → medium → large) floating above agent head
- Appears when status = "thinking"
- Fades in/out with opacity animation
- Billboard-aligned (always faces camera)

### Transition Strategy
- Keep simple AgentMesh as fallback (LOD level 0)
- GrabbyAvatar is LOD level 1, used when camera distance < 20 units
- Beyond 20 units: simplified representation (cylinder + label only)

---

## Phase 3: Robust Picking and Visual Polish

### Goal
Improve interaction quality and scene atmosphere.

### pickBestHex Enhancement

Port DeskClaw's `pickBestHexId` logic:

```typescript
function pickBestHex(intersections: Intersection[], camera: Camera): HexCoordinates | null {
  // When multiple hexes are hit (overlapping edges):
  // 1. For each intersection, get the hex's ground-center world position
  // 2. Project each center to camera NDC space
  // 3. Compare with cursor NDC position
  // 4. Return hex whose projected center is closest to cursor
}
```

### Camera Focus
- Double-click agent → smooth camera orbit to center on agent
- `focusOnAgent(agentId)`: lerp OrbitControls.target + zoom adjustment
- Keyboard: arrow keys to pan between agents

### Scene Atmosphere
- Add `THREE.FogExp2` for depth perception
- Hemisphere light (sky blue + ground warmth)
- Ground plane with subtle grid pattern (CSS-style dashed lines)
- Agent shadow projections (soft shadows via drei `ContactShadows`)

### Hover/Selection Polish
- Hover: hex lifts slightly (y += 0.15), emissive pulse
- Selected: sustained glow, status ring pulses
- Agent hover: tooltip-like info card (name, status, current task)

---

## Event Flow Architecture

```
WebSocket Event (workspace_message_created / agent:collaboration)
  |
  +-- WorkspaceDetail.tsx (event handler)
       |
       +-- store.handleChatEvent()  --> ChatPanel update
       |
       +-- hexCanvas3DRef.triggerMessageFlow(senderId, mentionIds)
            |
            +-- useMessageFlow.triggerFlow()
                 |
                 +-- BFS pathfind (topology edges)
                 +-- Create FlowState with world-space path
                 +-- MessageFlowManager renders FlowParticle
                      |
                      +-- useFrame: advance progress, lerp position
                      +-- On complete: burst effect + cleanup
```

For agent status updates (future):
```
WebSocket Event (agent:status_changed)
  |
  +-- WorkspaceDetail.tsx
       |
       +-- hexCanvas3DRef.setAgentStatus(agentId, status)
            |
            +-- AgentMesh receives new status prop
            +-- useAgentAnimation adjusts animations
            +-- ThoughtBubble appears/disappears
```

---

## Implementation Order

| Step | Files | Est. Time | Dependencies |
|------|-------|-----------|--------------|
| 1a | `constants.ts` | 30 min | None |
| 1b | `useMessageFlow.ts` | 1 hr | constants.ts |
| 1c | `FlowParticle.tsx` | 1 hr | useMessageFlow.ts |
| 1d | `MessageFlowManager.tsx` | 30 min | FlowParticle.tsx |
| 1e | Integrate into HexCanvas3D + WorkspaceDetail | 1 hr | All above |
| 2a | `useAgentAnimation.ts` | 1 hr | None |
| 2b | `GrabbyAvatar.tsx` | 2 hr | useAgentAnimation.ts, constants.ts |
| 2c | `ThoughtBubble.tsx` | 30 min | None |
| 2d | Update AgentMesh to use GrabbyAvatar | 30 min | All above |
| 3a | Enhance `useHex3DPick.ts` with pickBestHex | 1 hr | None |
| 3b | Scene atmosphere (HexScene.tsx) | 30 min | None |
| 3c | Hover/selection animations | 1 hr | useAgentAnimation.ts |
| 3d | Camera focus (CameraAnimator) | 30 min | None |

**Total estimated: ~11 hours of implementation**

---

## Key Decisions

1. **R3F over raw Three.js** - We already use R3F, and declarative components integrate better with React state. DeskClaw's raw Three.js approach in Vue is reference only.

2. **Shared geometries in constants.ts** - Like DeskClaw, we create geometries once and reuse. R3F's `<primitive>` or direct refs achieve this.

3. **BFS pathfinding on topology** - Reuse the topology edges (already available as props) for flow particle routing. No new graph structure needed.

4. **LOD for avatars** - Simple representation at distance, detailed Grabby up close. Prevents performance issues with many agents.

5. **Event-driven, not polling** - All 3D effects triggered by WebSocket events, not by polling API. Zero additional backend load.

6. **Max 20 concurrent flows** - Prevents performance degradation during heavy collaboration. Oldest flows are recycled.

---

## Performance Budget

| Metric | Target |
|--------|--------|
| Frame rate | 60fps with 20 agents + 10 active flows |
| Draw calls | < 100 (instanced hexes + shared avatar geometries) |
| Memory | < 50MB for 3D scene |
| First render | < 500ms (lazy-loaded Canvas already deferred) |

### Optimization Strategies
- Instanced meshes for hex tiles (already done via HexInstances)
- Shared geometries/materials for avatar parts (constants.ts)
- LOD switching for avatars based on camera distance
- Object pooling for flow particles (pre-allocate, reuse)
- `three-mesh-bvh` for raycast acceleration (already installed)
