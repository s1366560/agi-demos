import { hexDistance } from '@/components/workspace/hex/useHexLayout';

import type { TopologyEdge, TopologyNode, WorkspaceAgent, WorkspaceTask } from '@/types/workspace';

// ---------------------------------------------------------------------------
// Type aliases
// ---------------------------------------------------------------------------

export type ViewMode = '2d' | '3d';

export type SelectionState =
  | { kind: 'empty'; q: number; r: number }
  | { kind: 'blackboard'; q: number; r: number }
  | { kind: 'agent'; agentId: string }
  | { kind: 'node'; nodeId: string };

export type MoveMode = { kind: 'agent'; agentId: string } | { kind: 'node'; nodeId: string } | null;

export type PlacedAgent = WorkspaceAgent & { hex_q: number; hex_r: number };

export type PlacedNode = TopologyNode & { hex_q: number; hex_r: number };

export type HexEdge = TopologyEdge & {
  source_hex_q: number;
  source_hex_r: number;
  target_hex_q: number;
  target_hex_r: number;
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const HEX_SIZE = 56;
export const RESERVED_CENTER_KEY = '0,0';
export const DEFAULT_AGENT_COLOR = 'var(--color-primary-500, #1e3fae)';
export const HUMAN_SEAT_COLOR = 'var(--color-warning, #f59e0b)';
export const MAX_LAYOUT_RADIUS = 24;
export const MAX_RENDER_GRID_RADIUS = 26;

export const COLOR_SWATCHS = [
  'var(--color-primary-500, #1e3fae)',
  'var(--color-primary-400, #2563eb)',
  'var(--color-secondary-400, #7c3aed)',
  'var(--color-info, #0f766e)',
  'var(--color-warning, #d97706)',
  'var(--color-error, #dc2626)',
];

export const KEYBOARD_HINTS = [
  {
    keys: 'Arrow keys',
    labelKey: 'blackboard.arrangement.shortcuts.navigate',
    defaultLabel: 'Move focus',
  },
  {
    keys: 'Shift + Arrows',
    labelKey: 'blackboard.arrangement.shortcuts.pan',
    defaultLabel: 'Pan canvas',
  },
  {
    keys: 'Enter / Space',
    labelKey: 'blackboard.arrangement.shortcuts.activate',
    defaultLabel: 'Inspect focused hex',
  },
  { keys: '+ / -', labelKey: 'blackboard.arrangement.shortcuts.zoom', defaultLabel: 'Zoom' },
  { keys: '0', labelKey: 'blackboard.arrangement.shortcuts.reset', defaultLabel: 'Reset view' },
  {
    keys: 'A / C / H',
    labelKey: 'blackboard.arrangement.shortcuts.place',
    defaultLabel: 'Place items',
  },
  {
    keys: 'M / Delete',
    labelKey: 'blackboard.arrangement.shortcuts.edit',
    defaultLabel: 'Move or remove selected item',
  },
  {
    keys: '2 / 3 / Esc',
    labelKey: 'blackboard.arrangement.shortcuts.mode',
    defaultLabel: 'Switch modes or clear selection',
  },
] as const;

export const HEX_KEY_OFFSETS = {
  ArrowUp: { q: 0, r: -1 },
  ArrowDown: { q: 0, r: 1 },
  ArrowLeft: { q: -1, r: 0 },
  ArrowRight: { q: 1, r: 0 },
} as const;

// ---------------------------------------------------------------------------
// Props interface
// ---------------------------------------------------------------------------

export interface WorkstationArrangementBoardProps {
  tenantId: string;
  projectId: string;
  workspaceId: string;
  workspaceName: string;
  agentWorkspacePath: string;
  agents: WorkspaceAgent[];
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  tasks: WorkspaceTask[];
  onOpenBlackboard: () => void;
}

// ---------------------------------------------------------------------------
// Pure functions
// ---------------------------------------------------------------------------

export function coordKey(q: number, r: number): string {
  return [q, r].join(',');
}

export function hasHex(value: number | undefined): value is number {
  return typeof value === 'number';
}

export function isEditableTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  if (!element) {
    return false;
  }
  const tagName = element.tagName.toLowerCase();
  return (
    tagName === 'input' ||
    tagName === 'textarea' ||
    tagName === 'select' ||
    element.isContentEditable
  );
}

export function getNodeAccent(node: TopologyNode): string {
  if (node.node_type === 'human_seat') {
    return resolveColor(node.data.color, HUMAN_SEAT_COLOR);
  }
  if (node.node_type === 'objective') {
    return 'var(--color-primary-light)';
  }
  return 'var(--color-info)';
}

export function resolveColor(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim().length > 0 ? value : fallback;
}

export function getNodeLabel(node: TopologyNode, fallback: string): string {
  return node.title.trim() || fallback;
}

export function getGridRadius(agents: WorkspaceAgent[], nodes: TopologyNode[]): number {
  const furthestAgent = agents.reduce((maxDistance, agent) => {
    if (!hasHex(agent.hex_q) || !hasHex(agent.hex_r)) {
      return maxDistance;
    }
    return Math.max(maxDistance, hexDistance(0, 0, agent.hex_q, agent.hex_r));
  }, 0);

  const furthestNode = nodes.reduce((maxDistance, node) => {
    if (!hasHex(node.hex_q) || !hasHex(node.hex_r)) {
      return maxDistance;
    }
    return Math.max(maxDistance, hexDistance(0, 0, node.hex_q, node.hex_r));
  }, 0);

  return Math.min(MAX_RENDER_GRID_RADIUS, Math.max(6, furthestAgent, furthestNode) + 2);
}

export function isRenderablePlacement(q: number, r: number): boolean {
  return hexDistance(0, 0, q, r) <= MAX_LAYOUT_RADIUS;
}

export function isPlacedAgent(agent: WorkspaceAgent): agent is PlacedAgent {
  return (
    hasHex(agent.hex_q) &&
    hasHex(agent.hex_r) &&
    coordKey(agent.hex_q, agent.hex_r) !== RESERVED_CENTER_KEY &&
    isRenderablePlacement(agent.hex_q, agent.hex_r)
  );
}

export function isPlacedNode(node: TopologyNode): node is PlacedNode {
  return (
    hasHex(node.hex_q) &&
    hasHex(node.hex_r) &&
    coordKey(node.hex_q, node.hex_r) !== RESERVED_CENTER_KEY &&
    isRenderablePlacement(node.hex_q, node.hex_r)
  );
}

export function hasEdgeCoordinates(edge: TopologyEdge): edge is HexEdge {
  return (
    hasHex(edge.source_hex_q) &&
    hasHex(edge.source_hex_r) &&
    hasHex(edge.target_hex_q) &&
    hasHex(edge.target_hex_r) &&
    isRenderablePlacement(edge.source_hex_q, edge.source_hex_r) &&
    isRenderablePlacement(edge.target_hex_q, edge.target_hex_r)
  );
}
