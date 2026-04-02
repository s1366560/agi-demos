import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
  WheelEvent as ReactWheelEvent,
} from 'react';

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import {
  Bot,
  ExternalLink,
  Keyboard,
  Minus,
  Move,
  Plus,
  RotateCcw,
  Route,
  Trash2,
  User,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';

import { useWorkspaceActions } from '@/stores/workspace';

import { useLazyMessage } from '@/components/ui/lazyAntd';
import { AddAgentModal } from '@/components/workspace/AddAgentModal';
import { hexDistance, hexToPixel, generateGrid, getHexCorners } from '@/components/workspace/hex/useHexLayout';

import { getErrorMessage } from '@/types/common';
import type { TopologyEdge, TopologyNode, WorkspaceAgent, WorkspaceTask } from '@/types/workspace';

const HexCanvas3D = lazy(() =>
  import('@/components/workspace/hex3d/HexCanvas3D').then((module) => ({
    default: module.HexCanvas3D,
  }))
);

type ViewMode = '2d' | '3d';

type SelectionState =
  | { kind: 'empty'; q: number; r: number }
  | { kind: 'blackboard'; q: number; r: number }
  | { kind: 'agent'; agentId: string }
  | { kind: 'node'; nodeId: string };

type MoveMode =
  | { kind: 'agent'; agentId: string }
  | { kind: 'node'; nodeId: string }
  | null;

type PlacedAgent = WorkspaceAgent & { hex_q: number; hex_r: number };

type PlacedNode = TopologyNode & { hex_q: number; hex_r: number };

type HexEdge = TopologyEdge & {
  source_hex_q: number;
  source_hex_r: number;
  target_hex_q: number;
  target_hex_r: number;
};

const HEX_SIZE = 56;
const RESERVED_CENTER_KEY = '0,0';
const DEFAULT_AGENT_COLOR = 'var(--color-primary-500, #1e3fae)';
const HUMAN_SEAT_COLOR = 'var(--color-warning, #f59e0b)';
const MAX_LAYOUT_RADIUS = 24;
const MAX_RENDER_GRID_RADIUS = 26;
const COLOR_SWATCHS = [
  'var(--color-primary-500, #1e3fae)',
  'var(--color-primary-400, #2563eb)',
  'var(--color-secondary-400, #7c3aed)',
  'var(--color-info, #0f766e)',
  'var(--color-warning, #d97706)',
  'var(--color-error, #dc2626)',
];

const KEYBOARD_HINTS = [
  { keys: 'Arrow keys', labelKey: 'blackboard.arrangement.shortcuts.navigate', defaultLabel: 'Move focus' },
  { keys: 'Shift + Arrows', labelKey: 'blackboard.arrangement.shortcuts.pan', defaultLabel: 'Pan canvas' },
  { keys: 'Enter / Space', labelKey: 'blackboard.arrangement.shortcuts.activate', defaultLabel: 'Inspect focused hex' },
  { keys: '+ / -', labelKey: 'blackboard.arrangement.shortcuts.zoom', defaultLabel: 'Zoom' },
  { keys: '0', labelKey: 'blackboard.arrangement.shortcuts.reset', defaultLabel: 'Reset view' },
  { keys: 'A / C / H', labelKey: 'blackboard.arrangement.shortcuts.place', defaultLabel: 'Place items' },
  { keys: 'M / Delete', labelKey: 'blackboard.arrangement.shortcuts.edit', defaultLabel: 'Move or remove selected item' },
  { keys: '2 / 3 / Esc', labelKey: 'blackboard.arrangement.shortcuts.mode', defaultLabel: 'Switch modes or clear selection' },
] as const;

const HEX_KEY_OFFSETS = {
  ArrowUp: { q: 0, r: -1 },
  ArrowDown: { q: 0, r: 1 },
  ArrowLeft: { q: -1, r: 0 },
  ArrowRight: { q: 1, r: 0 },
} as const;

interface WorkstationArrangementBoardProps {
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

function coordKey(q: number, r: number): string {
  return [q, r].join(',');
}

function hasHex(value: number | undefined): value is number {
  return typeof value === 'number';
}

function isEditableTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  if (!element) {
    return false;
  }
  const tagName = element.tagName.toLowerCase();
  return tagName === 'input' || tagName === 'textarea' || tagName === 'select' || element.isContentEditable;
}

function getNodeAccent(node: TopologyNode): string {
  if (node.node_type === 'human_seat') {
    return resolveColor(node.data.color, HUMAN_SEAT_COLOR);
  }
  if (node.node_type === 'objective') {
    return 'var(--color-primary-light)';
  }
  return 'var(--color-info)';
}

function resolveColor(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim().length > 0 ? value : fallback;
}

function getNodeLabel(node: TopologyNode, fallback: string): string {
  return node.title.trim() || fallback;
}

function getGridRadius(agents: WorkspaceAgent[], nodes: TopologyNode[]): number {
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

function isRenderablePlacement(q: number, r: number): boolean {
  return hexDistance(0, 0, q, r) <= MAX_LAYOUT_RADIUS;
}

function isPlacedAgent(agent: WorkspaceAgent): agent is PlacedAgent {
  return (
    hasHex(agent.hex_q) &&
    hasHex(agent.hex_r) &&
    coordKey(agent.hex_q, agent.hex_r) !== RESERVED_CENTER_KEY &&
    isRenderablePlacement(agent.hex_q, agent.hex_r)
  );
}

function isPlacedNode(node: TopologyNode): node is PlacedNode {
  return (
    hasHex(node.hex_q) &&
    hasHex(node.hex_r) &&
    coordKey(node.hex_q, node.hex_r) !== RESERVED_CENTER_KEY &&
    isRenderablePlacement(node.hex_q, node.hex_r)
  );
}

function hasEdgeCoordinates(edge: TopologyEdge): edge is HexEdge {
  return (
    hasHex(edge.source_hex_q) &&
    hasHex(edge.source_hex_r) &&
    hasHex(edge.target_hex_q) &&
    hasHex(edge.target_hex_r) &&
    isRenderablePlacement(edge.source_hex_q, edge.source_hex_r) &&
    isRenderablePlacement(edge.target_hex_q, edge.target_hex_r)
  );
}

export function WorkstationArrangementBoard({
  tenantId,
  projectId,
  workspaceId,
  workspaceName,
  agentWorkspacePath,
  agents,
  nodes,
  edges,
  tasks,
  onOpenBlackboard,
}: WorkstationArrangementBoardProps) {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const {
    bindAgent,
    updateAgentBinding,
    unbindAgent,
    moveAgent,
    createTopologyNode,
    updateTopologyNode,
    deleteTopologyNode,
    selectHex,
    clearSelectedHex,
  } = useWorkspaceActions();

  const [viewMode, setViewMode] = useState<ViewMode>('2d');
  const [selection, setSelection] = useState<SelectionState | null>(null);
  const [moveMode, setMoveMode] = useState<MoveMode>(null);
  const [addAgentOpen, setAddAgentOpen] = useState(false);
  const [labelDraft, setLabelDraft] = useState('');
  const [colorDraft, setColorDraft] = useState(DEFAULT_AGENT_COLOR);
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [panning, setPanning] = useState(false);
  const [panAnchor, setPanAnchor] = useState({ x: 0, y: 0 });
  const [keyboardCursor, setKeyboardCursor] = useState({ q: 0, r: 0 });
  const [isBoardFocused, setIsBoardFocused] = useState(false);
  const isKeyboardGridActive = viewMode === '2d';
  const boardContainerRef = useRef<HTMLDivElement | null>(null);

  const gridRadius = useMemo(() => getGridRadius(agents, nodes), [agents, nodes]);
  const gridCells = useMemo(() => generateGrid(gridRadius), [gridRadius]);
  const gridHelpId = useMemo(() => `blackboard-grid-help-${workspaceId}`, [workspaceId]);
  const gridStatusId = useMemo(() => `blackboard-grid-status-${workspaceId}`, [workspaceId]);

  const placedAgents = useMemo(() => agents.filter(isPlacedAgent), [agents]);
  const placedNodes = useMemo(() => nodes.filter(isPlacedNode), [nodes]);

  const agentByCoord = useMemo(() => {
    const nextMap = new Map<string, WorkspaceAgent>();
    placedAgents.forEach((agent) => {
      nextMap.set(coordKey(agent.hex_q, agent.hex_r), agent);
    });
    return nextMap;
  }, [placedAgents]);

  const nodeByCoord = useMemo(() => {
    const nextMap = new Map<string, TopologyNode>();
    placedNodes.forEach((node) => {
      nextMap.set(coordKey(node.hex_q, node.hex_r), node);
    });
    return nextMap;
  }, [placedNodes]);

  const selectedAgent =
    selection?.kind === 'agent' ? agents.find((agent) => agent.id === selection.agentId) ?? null : null;
  const selectedNode =
    selection?.kind === 'node' ? nodes.find((node) => node.id === selection.nodeId) ?? null : null;

  const selectedHex = useMemo(() => {
    if (!selection) {
      return null;
    }
    if (selection.kind === 'empty' || selection.kind === 'blackboard') {
      return { q: selection.q, r: selection.r };
    }
    if (selection.kind === 'agent' && selectedAgent && hasHex(selectedAgent.hex_q) && hasHex(selectedAgent.hex_r)) {
      return { q: selectedAgent.hex_q, r: selectedAgent.hex_r };
    }
    if (selection.kind === 'node' && selectedNode && hasHex(selectedNode.hex_q) && hasHex(selectedNode.hex_r)) {
      return { q: selectedNode.hex_q, r: selectedNode.hex_r };
    }
    return null;
  }, [selectedAgent, selectedNode, selection]);

  const summary = useMemo(() => {
    const completedTasks = tasks.filter((task) => task.status === 'done').length;
    const humanSeats = nodes.filter((node) => node.node_type === 'human_seat').length;
    const corridors = nodes.filter((node) => node.node_type === 'corridor').length;
    return {
      completedTasks,
      humanSeats,
      corridors,
    };
  }, [nodes, tasks]);

  useEffect(() => {
    if (selection?.kind === 'agent' && selectedAgent == null) {
      setSelection(null);
      setMoveMode(null);
    }
  }, [selectedAgent, selection]);

  useEffect(() => {
    if (selection?.kind === 'node' && selectedNode == null) {
      setSelection(null);
      setMoveMode(null);
    }
  }, [selectedNode, selection]);

  useEffect(() => {
    if (!selection) {
      setLabelDraft('');
      setColorDraft(DEFAULT_AGENT_COLOR);
      return;
    }
    if (selection.kind === 'agent' && selectedAgent) {
      setLabelDraft(selectedAgent.label ?? selectedAgent.display_name ?? '');
      setColorDraft(selectedAgent.theme_color ?? DEFAULT_AGENT_COLOR);
      return;
    }
    if (selection.kind === 'node' && selectedNode) {
      setLabelDraft(selectedNode.title);
      setColorDraft(resolveColor(selectedNode.data.color, HUMAN_SEAT_COLOR));
      return;
    }
    setLabelDraft('');
    setColorDraft(DEFAULT_AGENT_COLOR);
  }, [selectedAgent, selectedNode, selection]);

  useEffect(() => {
    if (selectedHex) {
      selectHex(selectedHex.q, selectedHex.r);
      return;
    }
    clearSelectedHex();
  }, [clearSelectedHex, selectHex, selectedHex]);

  useEffect(() => {
    if (selectedHex) {
      setKeyboardCursor({ q: selectedHex.q, r: selectedHex.r });
    }
  }, [selectedHex]);

  useEffect(() => {
    if (!isKeyboardGridActive) {
      setIsBoardFocused(false);
    }
  }, [isKeyboardGridActive]);

  useEffect(() => {
    if (hexDistance(0, 0, keyboardCursor.q, keyboardCursor.r) > gridRadius) {
      setKeyboardCursor({ q: 0, r: 0 });
    }
  }, [gridRadius, keyboardCursor.q, keyboardCursor.r]);

  const resetView = useCallback(() => {
    setPan({ x: 0, y: 0 });
    setZoom(1);
  }, []);

  const nudgePan = useCallback((x: number, y: number) => {
    setPan((current) => ({ x: current.x + x, y: current.y + y }));
  }, []);

  const occupiedByOther = useCallback(
    (q: number, r: number, currentKey?: string | null) => {
      const targetKey = coordKey(q, r);
      if (targetKey === RESERVED_CENTER_KEY) {
        return true;
      }
      if (targetKey === currentKey) {
        return false;
      }
      return agentByCoord.has(targetKey) || nodeByCoord.has(targetKey);
    },
    [agentByCoord, nodeByCoord]
  );

  const handleMoveSelection = useCallback(
    async (q: number, r: number) => {
      if (!moveMode) {
        return;
      }

      if (moveMode.kind === 'agent') {
        const agent = agents.find((item) => item.id === moveMode.agentId);
        if (!agent) {
          return;
        }
        const currentKey =
          hasHex(agent.hex_q) && hasHex(agent.hex_r) ? coordKey(agent.hex_q, agent.hex_r) : null;
        if (occupiedByOther(q, r, currentKey)) {
          message?.warning(
            t('blackboard.arrangement.messages.slotUnavailable', 'That workstation is already occupied.')
          );
          return;
        }

        setPendingAction('move-agent');
        try {
          const updatedAgent = await moveAgent(
            tenantId,
            projectId,
            workspaceId,
            agent.id,
            q,
            r
          );
          setSelection({ kind: 'agent', agentId: updatedAgent.id });
          setMoveMode(null);
        } catch (error) {
          message?.error(getErrorMessage(error));
        } finally {
          setPendingAction(null);
        }
        return;
      }

      const node = nodes.find((item) => item.id === moveMode.nodeId);
      if (!node) {
        return;
      }
      const currentKey = hasHex(node.hex_q) && hasHex(node.hex_r) ? coordKey(node.hex_q, node.hex_r) : null;
      if (occupiedByOther(q, r, currentKey)) {
        message?.warning(
          t('blackboard.arrangement.messages.slotUnavailable', 'That workstation is already occupied.')
        );
        return;
      }

      const logicalPosition = hexToPixel(q, r, 1);
      setPendingAction('move-node');
      try {
        const updatedNode = await updateTopologyNode(workspaceId, node.id, {
          hex_q: q,
          hex_r: r,
          position_x: logicalPosition.x,
          position_y: logicalPosition.y,
        });
        setSelection({ kind: 'node', nodeId: updatedNode.id });
        setMoveMode(null);
      } catch (error) {
        message?.error(getErrorMessage(error));
      } finally {
        setPendingAction(null);
      }
    },
    [
      agents,
      message,
      moveAgent,
      moveMode,
      nodes,
      occupiedByOther,
      projectId,
      t,
      tenantId,
      updateTopologyNode,
      workspaceId,
    ]
  );

  const handleActivateHex = useCallback(
    async (q: number, r: number) => {
      setKeyboardCursor({ q, r });

      if (moveMode) {
        await handleMoveSelection(q, r);
        return;
      }

      const key = coordKey(q, r);
      if (key === RESERVED_CENTER_KEY) {
        setSelection({ kind: 'blackboard', q, r });
        onOpenBlackboard();
        return;
      }

      const agent = agentByCoord.get(key);
      if (agent) {
        setSelection({ kind: 'agent', agentId: agent.id });
        return;
      }

      const node = nodeByCoord.get(key);
      if (node) {
        setSelection({ kind: 'node', nodeId: node.id });
        return;
      }

      setSelection({ kind: 'empty', q, r });
    },
    [agentByCoord, handleMoveSelection, moveMode, nodeByCoord, onOpenBlackboard]
  );

  const handleCreateNode = useCallback(
    async (nodeType: TopologyNode['node_type'], targetHex?: { q: number; r: number }) => {
      const target =
        targetHex ?? (selection?.kind === 'empty' ? { q: selection.q, r: selection.r } : null);

      if (!target) {
        return;
      }
      const logicalPosition = hexToPixel(target.q, target.r, 1);
      const defaultTitle =
        nodeType === 'human_seat'
          ? t('blackboard.arrangement.defaults.humanSeat', 'Human seat')
          : t('blackboard.arrangement.defaults.corridor', 'Corridor');

      setPendingAction(`create-${nodeType}`);
      try {
        const createdNode = await createTopologyNode(workspaceId, {
          node_type: nodeType,
          title: defaultTitle,
          hex_q: target.q,
          hex_r: target.r,
          position_x: logicalPosition.x,
          position_y: logicalPosition.y,
          status: 'active',
          data: nodeType === 'human_seat' ? { color: HUMAN_SEAT_COLOR } : {},
        });
        setSelection({ kind: 'node', nodeId: createdNode.id });
      } catch (error) {
        message?.error(getErrorMessage(error));
      } finally {
        setPendingAction(null);
      }
    },
    [createTopologyNode, message, selection, t, workspaceId]
  );

  const handleAddAgent = useCallback(
    async (data: { agent_id: string; display_name?: string; description?: string }) => {
      if (selection?.kind !== 'empty') {
        return;
      }
      const agent = await bindAgent(tenantId, projectId, workspaceId, {
        ...data,
        hex_q: selection.q,
        hex_r: selection.r,
      });
      setSelection({ kind: 'agent', agentId: agent.id });
      message?.success(
        t('blackboard.arrangement.messages.agentPlaced', 'Agent placed on the workstation.')
      );
    },
    [bindAgent, message, projectId, selection, t, tenantId, workspaceId]
  );

  const handleSaveSelection = useCallback(async () => {
    if (selection?.kind === 'agent' && selectedAgent) {
      setPendingAction('save-agent');
      try {
        const updatePayload: Parameters<typeof updateAgentBinding>[4] = {
          theme_color: colorDraft,
        };
        const nextLabel = labelDraft.trim();
        if (nextLabel.length > 0) {
          updatePayload.label = nextLabel;
        }
        await updateAgentBinding(
          tenantId,
          projectId,
          workspaceId,
          selectedAgent.id,
          updatePayload
        );
        message?.success(
          t('blackboard.arrangement.messages.agentUpdated', 'Agent styling updated.')
        );
      } catch (error) {
        message?.error(getErrorMessage(error));
      } finally {
        setPendingAction(null);
      }
      return;
    }

    if (selection?.kind === 'node' && selectedNode) {
      setPendingAction('save-node');
      try {
        const nextData =
          selectedNode.node_type === 'human_seat'
            ? { ...selectedNode.data, color: colorDraft }
            : selectedNode.data;
        await updateTopologyNode(workspaceId, selectedNode.id, {
          title: labelDraft.trim() || selectedNode.title,
          data: nextData,
        });
        message?.success(
          t('blackboard.arrangement.messages.nodeUpdated', 'Seat details updated.')
        );
      } catch (error) {
        message?.error(getErrorMessage(error));
      } finally {
        setPendingAction(null);
      }
    }
  }, [
    colorDraft,
    labelDraft,
    message,
    projectId,
    selectedAgent,
    selectedNode,
    selection,
    t,
    tenantId,
    updateAgentBinding,
    updateTopologyNode,
    workspaceId,
  ]);

  const handleDeleteSelection = useCallback(async () => {
    if (selection?.kind === 'agent' && selectedAgent) {
      setPendingAction('delete-agent');
      try {
        await unbindAgent(tenantId, projectId, workspaceId, selectedAgent.id);
        setSelection(null);
        setMoveMode(null);
        message?.success(
          t('blackboard.arrangement.messages.agentRemoved', 'Agent removed from the workstation.')
        );
      } catch (error) {
        message?.error(getErrorMessage(error));
      } finally {
        setPendingAction(null);
      }
      return;
    }

    if (selection?.kind === 'node' && selectedNode) {
      setPendingAction('delete-node');
      try {
        await deleteTopologyNode(workspaceId, selectedNode.id);
        setSelection(null);
        setMoveMode(null);
        message?.success(
          t('blackboard.arrangement.messages.nodeRemoved', 'Seat removed from the workstation.')
        );
      } catch (error) {
        message?.error(getErrorMessage(error));
      } finally {
        setPendingAction(null);
      }
    }
  }, [
    deleteTopologyNode,
    message,
    projectId,
    selectedAgent,
    selectedNode,
    selection,
    t,
    tenantId,
    unbindAgent,
    workspaceId,
  ]);

  const beginMoveMode = useCallback(() => {
    if (selection?.kind === 'agent') {
      setMoveMode({ kind: 'agent', agentId: selection.agentId });
      return;
    }
    if (selection?.kind === 'node') {
      setMoveMode({ kind: 'node', nodeId: selection.nodeId });
    }
  }, [selection]);

  const handleBoardKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLDivElement>) => {
      if (isEditableTarget(event.target)) {
        return;
      }

      if (event.key === 'Escape') {
        setMoveMode(null);
        setSelection(null);
        return;
      }

      if (event.key === '2') {
        setViewMode('2d');
        return;
      }

      if (event.key === '3') {
        setViewMode('3d');
        return;
      }

      if (event.key === '0') {
        event.preventDefault();
        resetView();
        return;
      }

      if (event.key === '+' || event.key === '=') {
        event.preventDefault();
        setZoom((current) => Math.min(2.2, current + 0.15));
        return;
      }

      if (event.key === '-') {
        event.preventDefault();
        setZoom((current) => Math.max(0.55, current - 0.15));
        return;
      }

      if (event.shiftKey && event.key in HEX_KEY_OFFSETS) {
        event.preventDefault();

        if (event.key === 'ArrowUp') {
          nudgePan(0, 28);
          return;
        }
        if (event.key === 'ArrowDown') {
          nudgePan(0, -28);
          return;
        }
        if (event.key === 'ArrowLeft') {
          nudgePan(28, 0);
          return;
        }
        if (event.key === 'ArrowRight') {
          nudgePan(-28, 0);
        }
        return;
      }

      if (viewMode === '2d' && event.key in HEX_KEY_OFFSETS) {
        event.preventDefault();
        setKeyboardCursor((current) => {
          const offset = HEX_KEY_OFFSETS[event.key as keyof typeof HEX_KEY_OFFSETS];
          const next = { q: current.q + offset.q, r: current.r + offset.r };

          if (hexDistance(0, 0, next.q, next.r) > gridRadius) {
            return current;
          }

          return next;
        });
        return;
      }

      if (viewMode === '2d' && (event.key === 'Enter' || event.key === ' ')) {
        event.preventDefault();
        void handleActivateHex(keyboardCursor.q, keyboardCursor.r);
        return;
      }

      if (selection?.kind === 'empty' && event.key.toLowerCase() === 'a') {
        event.preventDefault();
        setAddAgentOpen(true);
        return;
      }

      if (
        selection?.kind !== 'empty' &&
        event.key.toLowerCase() === 'a' &&
        !agentByCoord.has(coordKey(keyboardCursor.q, keyboardCursor.r)) &&
        !nodeByCoord.has(coordKey(keyboardCursor.q, keyboardCursor.r)) &&
        coordKey(keyboardCursor.q, keyboardCursor.r) !== RESERVED_CENTER_KEY
      ) {
        event.preventDefault();
        setSelection({ kind: 'empty', q: keyboardCursor.q, r: keyboardCursor.r });
        setAddAgentOpen(true);
        return;
      }

      if (selection?.kind === 'empty' && event.key.toLowerCase() === 'c') {
        event.preventDefault();
        void handleCreateNode('corridor');
        return;
      }

      if (
        selection?.kind !== 'empty' &&
        event.key.toLowerCase() === 'c' &&
        !agentByCoord.has(coordKey(keyboardCursor.q, keyboardCursor.r)) &&
        !nodeByCoord.has(coordKey(keyboardCursor.q, keyboardCursor.r)) &&
        coordKey(keyboardCursor.q, keyboardCursor.r) !== RESERVED_CENTER_KEY
      ) {
        event.preventDefault();
        setSelection({ kind: 'empty', q: keyboardCursor.q, r: keyboardCursor.r });
        void handleCreateNode('corridor', keyboardCursor);
        return;
      }

      if (selection?.kind === 'empty' && event.key.toLowerCase() === 'h') {
        event.preventDefault();
        void handleCreateNode('human_seat');
        return;
      }

      if (
        selection?.kind !== 'empty' &&
        event.key.toLowerCase() === 'h' &&
        !agentByCoord.has(coordKey(keyboardCursor.q, keyboardCursor.r)) &&
        !nodeByCoord.has(coordKey(keyboardCursor.q, keyboardCursor.r)) &&
        coordKey(keyboardCursor.q, keyboardCursor.r) !== RESERVED_CENTER_KEY
      ) {
        event.preventDefault();
        setSelection({ kind: 'empty', q: keyboardCursor.q, r: keyboardCursor.r });
        void handleCreateNode('human_seat', keyboardCursor);
        return;
      }

      if (
        (selection?.kind === 'agent' || selection?.kind === 'node') &&
        event.key.toLowerCase() === 'm'
      ) {
        event.preventDefault();
        beginMoveMode();
        return;
      }

      if (
        (selection?.kind === 'agent' || selection?.kind === 'node') &&
        (event.key === 'Delete' || event.key === 'Backspace')
      ) {
        event.preventDefault();
        void handleDeleteSelection();
      }
    },
    [
      beginMoveMode,
      agentByCoord,
      gridRadius,
      handleActivateHex,
      handleCreateNode,
      handleDeleteSelection,
      keyboardCursor,
      nodeByCoord,
      nudgePan,
      resetView,
      selection,
      viewMode,
    ]
  );

  const handleWheel = useCallback((event: ReactWheelEvent<SVGSVGElement>) => {
    event.preventDefault();
    const delta = event.deltaY > 0 ? -0.1 : 0.1;
    setZoom((current) => Math.max(0.55, Math.min(2.2, current + delta)));
  }, []);

  const handlePointerDown = useCallback((event: ReactPointerEvent<SVGSVGElement>) => {
    if (event.target instanceof Element && event.target.closest('[data-hex-cell="true"]')) {
      return;
    }
    boardContainerRef.current?.focus();
    setPanning(true);
    setPanAnchor({ x: event.clientX - pan.x, y: event.clientY - pan.y });
  }, [pan.x, pan.y]);

  const handlePointerMove = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>) => {
      if (!panning) {
        return;
      }
      setPan({ x: event.clientX - panAnchor.x, y: event.clientY - panAnchor.y });
    },
    [panAnchor.x, panAnchor.y, panning]
  );

  const edgeElements = useMemo(
    () =>
      edges
        .filter(hasEdgeCoordinates)
        .map((edge) => {
          const from = hexToPixel(edge.source_hex_q, edge.source_hex_r, HEX_SIZE);
          const to = hexToPixel(edge.target_hex_q, edge.target_hex_r, HEX_SIZE);
          return (
            <g key={edge.id}>
              <line
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                stroke="var(--color-success)"
                strokeOpacity={0.24}
                strokeWidth={10}
                strokeLinecap="round"
              />
              <line
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                stroke="var(--color-info)"
                strokeOpacity={0.9}
                strokeWidth={2.5}
                strokeLinecap="round"
                strokeDasharray={edge.direction === 'bidirectional' ? '0' : '12 8'}
              />
            </g>
          );
        }),
    [edges]
  );

  const cellElements = useMemo(
    () =>
      gridCells.map(({ q, r }) => {
        const key = coordKey(q, r);
        const center = hexToPixel(q, r, HEX_SIZE);
        const points = getHexCorners(center.x, center.y, HEX_SIZE)
          .map((corner) => [corner.x, corner.y].join(','))
          .join(' ');
        const isCenter = key === RESERVED_CENTER_KEY;
        const agent = agentByCoord.get(key);
        const node = nodeByCoord.get(key);
        const isSelected = selectedHex != null && selectedHex.q === q && selectedHex.r === r;
        const isKeyboardTarget = keyboardCursor.q === q && keyboardCursor.r === r;
        const isMoveTarget = moveMode != null && selection?.kind === 'empty' && selection.q === q && selection.r === r;

        return (
          <g
            key={key}
            data-hex-cell="true"
            onClick={(event) => {
              event.stopPropagation();
              boardContainerRef.current?.focus();
              setKeyboardCursor({ q, r });
              void handleActivateHex(q, r);
            }}
          >
            <polygon
              points={points}
              fill={
                isCenter
                  ? 'var(--color-primary-400)'
                  : isSelected || isKeyboardTarget
                    ? 'var(--color-primary-light)'
                    : agent || node
                      ? 'var(--color-surface-light)'
                      : 'transparent'
              }
              fillOpacity={
                isCenter
                  ? 0.16
                  : isSelected
                    ? 0.12
                    : isKeyboardTarget
                      ? 0.07
                      : agent || node
                        ? 0.04
                        : 0
              }
              stroke={
                isCenter || isSelected || isKeyboardTarget
                  ? 'var(--color-primary-300)'
                  : 'var(--color-border-separator)'
              }
              strokeOpacity={isCenter ? 0.82 : isSelected ? 0.92 : isKeyboardTarget ? 0.72 : 0.24}
              strokeWidth={isCenter ? 3 : isSelected ? 2.5 : isKeyboardTarget ? 2 : 1}
              strokeDasharray={isMoveTarget ? '10 6' : undefined}
              className="transition-all duration-200 motion-reduce:transition-none"
            />

            {isCenter && (
              <g>
                <text
                  x={center.x}
                  y={center.y - 8}
                  textAnchor="middle"
                  className="fill-[var(--color-text-inverse)] text-[16px] font-semibold"
                >
                  {t('blackboard.arrangement.centerTitle', 'Central blackboard')}
                </text>
                <text
                  x={center.x}
                  y={center.y + 18}
                  textAnchor="middle"
                  className="fill-[var(--color-primary-200)] text-[12px]"
                >
                  {t('blackboard.arrangement.centerSubtitle', 'Open discussion, goals, and execution')}
                </text>
              </g>
            )}

            {agent && (
              <g>
                <circle
                  cx={center.x}
                  cy={center.y - 10}
                  r={22}
                  fill={agent.theme_color ?? DEFAULT_AGENT_COLOR}
                  fillOpacity={0.16}
                  stroke={agent.theme_color ?? DEFAULT_AGENT_COLOR}
                  strokeWidth={2}
                />
                <text
                  x={center.x}
                  y={center.y - 10}
                  textAnchor="middle"
                  dominantBaseline="central"
                  className="fill-white text-[18px] font-semibold"
                >
                  {(agent.label ?? agent.display_name ?? agent.agent_id).charAt(0).toUpperCase()}
                </text>
                <text
                  x={center.x}
                  y={center.y + 28}
                  textAnchor="middle"
                  className="fill-[var(--color-text-inverse)] text-[12px] font-medium"
                >
                  {(agent.label ?? agent.display_name ?? agent.agent_id).slice(0, 16)}
                </text>
              </g>
            )}

            {node && node.node_type === 'corridor' && (
              <g>
                <line
                  x1={center.x - 18}
                  y1={center.y}
                  x2={center.x + 18}
                  y2={center.y}
                  stroke="var(--color-info)"
                  strokeOpacity={0.95}
                  strokeWidth={3}
                  strokeLinecap="round"
                />
                <line
                  x1={center.x}
                  y1={center.y - 18}
                  x2={center.x}
                  y2={center.y + 18}
                  stroke="var(--color-info)"
                  strokeOpacity={0.4}
                  strokeWidth={3}
                  strokeLinecap="round"
                />
                <text
                  x={center.x}
                  y={center.y + 30}
                  textAnchor="middle"
                  className="fill-[var(--color-text-inverse)] text-[11px] font-medium"
                >
                  {getNodeLabel(node, t('blackboard.arrangement.defaults.corridor', 'Corridor')).slice(0, 16)}
                </text>
              </g>
            )}

            {node && node.node_type !== 'corridor' && (
              <g>
                <circle
                  cx={center.x}
                  cy={center.y - 10}
                  r={18}
                  fill={getNodeAccent(node)}
                  fillOpacity={0.16}
                  stroke={getNodeAccent(node)}
                  strokeWidth={2}
                />
                <text
                  x={center.x}
                  y={center.y - 10}
                  textAnchor="middle"
                  dominantBaseline="central"
                  className="fill-white text-[14px] font-semibold"
                >
                  {node.node_type === 'human_seat' ? 'H' : 'O'}
                </text>
                <text
                  x={center.x}
                  y={center.y + 28}
                  textAnchor="middle"
                  className="fill-[var(--color-text-inverse)] text-[11px] font-medium"
                >
                  {getNodeLabel(
                    node,
                    node.node_type === 'human_seat'
                      ? t('blackboard.arrangement.defaults.humanSeat', 'Human seat')
                      : t('blackboard.arrangement.defaults.objective', 'Objective')
                  ).slice(0, 16)}
                </text>
              </g>
            )}
          </g>
        );
      }),
    [
      agentByCoord,
      gridCells,
      handleActivateHex,
      keyboardCursor.q,
      keyboardCursor.r,
      moveMode,
      nodeByCoord,
      selectedHex,
      selection,
      t,
    ]
  );

  const svgTransform = useMemo(
    () =>
      ['translate(', pan.x.toString(), ', ', pan.y.toString(), ') scale(', zoom.toString(), ')'].join(
        ''
      ),
    [pan.x, pan.y, zoom]
  );

  const keyboardCursorSummary = useMemo(() => {
    const key = coordKey(keyboardCursor.q, keyboardCursor.r);
    const agent = agentByCoord.get(key);
    const node = nodeByCoord.get(key);

    if (key === RESERVED_CENTER_KEY) {
      return t(
        'blackboard.arrangement.focus.blackboard',
        'Focused on the central blackboard. Press Enter to open the command modal.'
      );
    }

    if (agent) {
      return t('blackboard.arrangement.focus.agent', {
        defaultValue: 'Focused on agent {{name}} at q {{q}}, r {{r}}.',
        name: agent.label ?? agent.display_name ?? agent.agent_id,
        q: keyboardCursor.q,
        r: keyboardCursor.r,
      });
    }

    if (node) {
      return t('blackboard.arrangement.focus.node', {
        defaultValue: 'Focused on {{name}} at q {{q}}, r {{r}}.',
        name: getNodeLabel(
          node,
          node.node_type === 'human_seat'
            ? t('blackboard.arrangement.defaults.humanSeat', 'Human seat')
            : t('blackboard.arrangement.defaults.corridor', 'Corridor')
        ),
        q: keyboardCursor.q,
        r: keyboardCursor.r,
      });
    }

    return t('blackboard.arrangement.focus.empty', {
      defaultValue: 'Focused on empty hex q {{q}}, r {{r}}.',
      q: keyboardCursor.q,
      r: keyboardCursor.r,
    });
  }, [agentByCoord, keyboardCursor.q, keyboardCursor.r, nodeByCoord, t]);

  return (
    <section className="flex flex-col h-full rounded-3xl border border-border-light bg-surface-light p-4 shadow-lg transition-colors duration-200 dark:border-border-dark dark:bg-surface-dark sm:p-5">
      <div className="flex flex-col gap-4 border-b border-border-light pb-4 dark:border-border-dark lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-2">
          <div className="text-[11px] uppercase tracking-[0.28em] text-primary/75 dark:text-primary/80">
            {t('blackboard.arrangement.eyebrow', 'Workstation arrangement')}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-2xl font-semibold text-text-primary dark:text-text-inverse">
              {workspaceName}
            </h2>
            <span className="rounded-full border border-success/25 bg-success/10 px-3 py-1 text-xs font-medium text-status-text-success dark:text-status-text-success-dark">
              {t('blackboard.arrangement.syncState', 'Live topology sync')}
            </span>
            {moveMode && (
              <span className="rounded-full border border-warning/25 bg-warning/10 px-3 py-1 text-xs font-medium text-status-text-warning dark:text-status-text-warning-dark">
                {t('blackboard.arrangement.moveMode', 'Move mode: click a free hex')}
              </span>
            )}
          </div>
          <p className="max-w-3xl text-sm leading-7 text-text-secondary dark:text-text-secondary">
            {t(
              'blackboard.arrangement.description',
              'Place AI employees, human seats, and corridor nodes on a shared command grid, then jump straight into the central blackboard when coordination needs more depth.'
            )}
          </p>
        </div>

        <div className="flex flex-col gap-3 lg:min-w-[320px] lg:items-end">
          <div className="flex flex-wrap justify-end gap-2">
            <span className="rounded-2xl border border-border-light bg-surface-muted px-3 py-2 text-xs text-text-secondary dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-secondary">
              {t('blackboard.arrangement.metrics.agents', '{{count}} agents', { count: agents.length })}
            </span>
            <span className="rounded-2xl border border-border-light bg-surface-muted px-3 py-2 text-xs text-text-secondary dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-secondary">
              {t('blackboard.arrangement.metrics.seats', '{{count}} human seats', {
                count: summary.humanSeats,
              })}
            </span>
            <span className="rounded-2xl border border-border-light bg-surface-muted px-3 py-2 text-xs text-text-secondary dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-secondary">
              {t('blackboard.arrangement.metrics.corridors', '{{count}} corridors', {
                count: summary.corridors,
              })}
            </span>
            <span className="rounded-2xl border border-border-light bg-surface-muted px-3 py-2 text-xs text-text-secondary dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-secondary">
              {t('blackboard.arrangement.metrics.tasks', '{{done}} / {{total}} tasks done', {
                done: summary.completedTasks,
                total: tasks.length,
              })}
            </span>
          </div>

          <div className="flex flex-wrap items-center justify-end gap-2">
            <div className="inline-flex rounded-2xl border border-border-light bg-surface-muted p-1 dark:border-border-dark dark:bg-surface-dark-alt">
              {(['2d', '3d'] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => {
                    setViewMode(mode);
                  }}
                  className={`min-h-10 rounded-[14px] px-4 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 ${
                    viewMode === mode
                      ? 'bg-primary text-white shadow-primary'
                      : 'text-text-secondary hover:bg-surface-light hover:text-text-primary dark:text-text-muted dark:hover:bg-surface-elevated dark:hover:text-text-inverse'
                  }`}
                >
                  {mode === '2d'
                    ? t('blackboard.arrangement.modes.twoD', '2D layout')
                    : t('blackboard.arrangement.modes.threeD', '3D view')}
                </button>
              ))}
            </div>

            <button
              type="button"
              onClick={() => {
                setZoom((current) => Math.max(0.55, current - 0.15));
              }}
              disabled={viewMode !== '2d'}
              className="inline-flex min-h-10 items-center gap-2 rounded-2xl border border-border-light bg-surface-muted px-3 text-sm text-text-secondary transition hover:bg-surface-light disabled:cursor-not-allowed disabled:opacity-40 dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-secondary dark:hover:bg-surface-elevated"
            >
              <ZoomOut className="h-4 w-4" />
              <Minus className="h-3 w-3" />
            </button>

            <button
              type="button"
              onClick={() => {
                setZoom((current) => Math.min(2.2, current + 0.15));
              }}
              disabled={viewMode !== '2d'}
              className="inline-flex min-h-10 items-center gap-2 rounded-2xl border border-border-light bg-surface-muted px-3 text-sm text-text-secondary transition hover:bg-surface-light disabled:cursor-not-allowed disabled:opacity-40 dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-secondary dark:hover:bg-surface-elevated"
            >
              <ZoomIn className="h-4 w-4" />
              <Plus className="h-3 w-3" />
            </button>

            <button
              type="button"
              onClick={resetView}
              className="inline-flex min-h-10 items-center gap-2 rounded-2xl border border-border-light bg-surface-muted px-4 text-sm text-text-secondary transition hover:bg-surface-light dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-secondary dark:hover:bg-surface-elevated"
            >
              <RotateCcw className="h-4 w-4" />
              {t('blackboard.arrangement.resetView', 'Reset view')}
            </button>
          </div>
        </div>
      </div>

      <div className="mt-4 flex-1 min-h-0 grid gap-4 xl:grid-cols-[minmax(0,1fr)_280px]">
        <div className="flex flex-col h-full overflow-hidden rounded-[24px] border border-border-light bg-surface-light dark:border-border-dark dark:bg-background-dark">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-light px-4 py-3 dark:border-border-dark">
            <div>
              <div className="text-sm font-medium text-text-primary dark:text-text-inverse">
                {t('blackboard.arrangement.canvasTitle', 'Command grid')}
              </div>
              <div className="text-xs text-text-muted dark:text-text-muted">
                {t(
                  'blackboard.arrangement.canvasSubtitle',
                  'Select a hex to stage a new seat, update an agent, or drill into the blackboard.'
                )}
              </div>
            </div>
            <div className="flex items-center gap-2">
              {isBoardFocused && isKeyboardGridActive && (
                <span className="max-w-full truncate rounded-full border border-info/25 bg-info/10 px-3 py-1 text-[11px] font-medium text-status-text-info dark:text-status-text-info-dark sm:max-w-[28rem]">
                  {keyboardCursorSummary}
                </span>
              )}
            <button
              type="button"
              onClick={onOpenBlackboard}
              className="inline-flex min-h-10 items-center gap-2 rounded-2xl border border-primary/20 bg-primary/10 px-4 text-sm font-medium text-primary transition hover:bg-primary/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:text-primary-200"
            >
              {t('blackboard.openBoard', 'Open central blackboard')}
            </button>
            </div>
          </div>

          {!isKeyboardGridActive && (
            <p className="text-xs text-text-secondary dark:text-text-muted px-4 py-2">
              {t(
                'blackboard.arrangement.threeDPreviewNote',
                '3D view is preview only. Use pointer controls here, or switch back to 2D for keyboard editing.'
              )}
            </p>
          )}

          <div className="relative flex-1 min-h-[280px] w-full">
              <div id={gridHelpId} className="sr-only">
                {isKeyboardGridActive
                  ? t(
                      'blackboard.arrangement.keyboardHint',
                      'Use arrow keys to move keyboard focus across the grid, Enter to inspect a hex, Shift and arrow keys to pan, and the action shortcuts only while this grid is focused.'
                    )
                  : t(
                      'blackboard.arrangement.threeDKeyboardHint',
                      'Three-dimensional view is preview only. Use pointer controls here, or switch back to 2D to move across hexes and edit placements with the keyboard.'
                    )}
              </div>
              {isKeyboardGridActive && (
                <div id={gridStatusId} aria-live="polite" className="sr-only">
                  {keyboardCursorSummary}
                </div>
              )}
            {viewMode === '2d' ? (
              <div
                ref={boardContainerRef}
                tabIndex={0}
                role="group"
                aria-label={t('blackboard.arrangement.ariaLabel', 'Interactive workstation arrangement grid')}
                aria-roledescription={t('blackboard.arrangement.roleDescription', 'hex grid')}
                aria-describedby={`${gridHelpId} ${gridStatusId}`}
                onFocus={() => {
                  setIsBoardFocused(true);
                }}
                onBlur={(event) => {
                  if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                    setIsBoardFocused(false);
                  }
                }}
                onKeyDown={handleBoardKeyDown}
                className="h-full w-full rounded-[inherit] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset"
              >
                <svg
                  className="h-full w-full touch-none"
                  role="img"
                  aria-hidden="true"
                  viewBox="-760 -560 1520 1120"
                  onWheel={handleWheel}
                  onPointerDown={handlePointerDown}
                  onPointerMove={handlePointerMove}
                  onPointerUp={() => {
                    setPanning(false);
                  }}
                  onPointerLeave={() => {
                    setPanning(false);
                  }}
                >
                  <defs>
                    <radialGradient id="blackboard-grid-glow">
                      <stop offset="0%" stopColor="rgba(30, 63, 174, 0.12)" />
                      <stop offset="100%" stopColor="rgba(30, 63, 174, 0)" />
                    </radialGradient>
                  </defs>
                  <rect x={-760} y={-560} width={1520} height={1120} fill="url(#blackboard-grid-glow)" />
                  <g transform={svgTransform}>
                    {edgeElements}
                    {cellElements}
                  </g>
                </svg>
              </div>
            ) : (
              <div
                tabIndex={-1}
                role="group"
                aria-label={t('blackboard.arrangement.threeDAriaLabel', 'Three-dimensional workstation arrangement')}
                aria-describedby={gridHelpId}
                className="h-full w-full rounded-[inherit]"
              >
                <Suspense
                  fallback={
                    <div className="flex h-full items-center justify-center bg-surface-muted text-sm text-text-secondary dark:bg-background-dark dark:text-text-secondary">
                      {t('common.loading', 'Loading…')}
                    </div>
                  }
                >
                  <HexCanvas3D
                    agents={placedAgents}
                    nodes={placedNodes}
                    edges={edges}
                    gridRadius={gridRadius}
                    onSelectHex={(q, r) => {
                      setKeyboardCursor({ q, r });
                      void handleActivateHex(q, r);
                    }}
                  />
                </Suspense>
              </div>
            )}

            {selection == null && (
              <div className="pointer-events-none absolute inset-x-4 bottom-4 rounded-2xl border border-border-light/80 bg-surface-light/95 px-4 py-3 text-sm text-text-secondary shadow-md dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-secondary">
                {t(
                  'blackboard.arrangement.emptySelectionHint',
                  'Start by selecting an empty hex, an AI employee, or the center board.'
                )}
              </div>
            )}
          </div>
        </div>

        <aside className="hidden rounded-[24px] border border-border-light bg-surface-muted p-4 dark:border-border-dark dark:bg-surface-dark-alt xl:block">
          <div className="flex items-center gap-2 text-sm font-medium text-text-primary dark:text-text-inverse">
            <Keyboard className="h-4 w-4 text-primary dark:text-primary-300" />
            {t('blackboard.arrangement.shortcutTitle', 'Keyboard map')}
          </div>
          <div className="mt-4 space-y-2">
            {KEYBOARD_HINTS.map(({ keys, labelKey, defaultLabel }) => (
              <div
                key={keys}
                className="flex items-center justify-between rounded-2xl border border-border-light bg-surface-light px-3 py-2 text-xs text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-secondary"
              >
                <span>{t(labelKey, defaultLabel)}</span>
                <kbd className="rounded-lg border border-border-light bg-surface-muted px-2 py-1 font-mono text-[11px] text-text-primary dark:border-border-dark dark:bg-surface-elevated dark:text-text-inverse">
                  {keys}
                </kbd>
              </div>
            ))}
          </div>

          <div className="mt-4 rounded-2xl border border-border-light bg-surface-light p-3 text-xs leading-6 text-text-muted dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
            {moveMode
              ? t(
                  'blackboard.arrangement.moveHint',
                  'Move mode is active. Choose a free hex or press Esc to cancel.'
                )
              : t(
                  'blackboard.arrangement.staticHint',
                  'The center hex always opens the shared blackboard. Workstation edits stay on this surface.'
                )}
          </div>
        </aside>
      </div>

      <div className="mt-4 flex-shrink-0 rounded-[24px] border border-border-light bg-surface-muted p-4 dark:border-border-dark dark:bg-surface-dark-alt">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="text-sm font-medium text-text-primary dark:text-text-inverse">
              {selection?.kind === 'agent' && selectedAgent
                ? selectedAgent.label ?? selectedAgent.display_name ?? selectedAgent.agent_id
                : selection?.kind === 'node' && selectedNode
                  ? getNodeLabel(
                      selectedNode,
                      selectedNode.node_type === 'human_seat'
                        ? t('blackboard.arrangement.defaults.humanSeat', 'Human seat')
                        : t('blackboard.arrangement.defaults.corridor', 'Corridor')
                    )
                  : selection?.kind === 'blackboard'
                    ? t('blackboard.arrangement.centerTitle', 'Central blackboard')
                    : selection?.kind === 'empty'
                      ? t('blackboard.arrangement.emptySlot', 'Empty workstation')
                      : t('blackboard.arrangement.drawerTitle', 'Action drawer')}
            </div>
            <div className="mt-1 text-xs text-text-muted dark:text-text-muted">
              {selectedHex
                ? t('blackboard.arrangement.coordinates', 'Hex {{q}}, {{r}}', selectedHex)
                : t(
                    'blackboard.arrangement.drawerSubtitle',
                    'Selection-aware actions appear here so the grid stays focused.'
                  )}
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            {selection?.kind === 'blackboard' && (
              <button
                type="button"
                onClick={onOpenBlackboard}
                className="inline-flex min-h-10 items-center rounded-2xl border border-primary/20 bg-primary/10 px-4 text-sm font-medium text-primary transition hover:bg-primary/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:text-primary-200"
              >
                {t('blackboard.openBoard', 'Open central blackboard')}
              </button>
            )}

            {selection?.kind === 'agent' && (
              <>
                <Link
                  to={agentWorkspacePath}
                  className="inline-flex min-h-10 items-center gap-2 rounded-2xl border border-border-light bg-surface-light px-4 text-sm font-medium text-text-primary transition hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-elevated"
                >
                  <ExternalLink className="h-4 w-4" />
                  {t('blackboard.arrangement.openWorkspace', 'Open workspace')}
                </Link>
                <button
                  type="button"
                  onClick={beginMoveMode}
                  className="inline-flex min-h-10 items-center gap-2 rounded-2xl border border-border-light bg-surface-light px-4 text-sm font-medium text-text-primary transition hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-elevated"
                >
                  <Move className="h-4 w-4" />
                  {t('blackboard.arrangement.actions.move', 'Move')}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    void handleDeleteSelection();
                  }}
                  disabled={pendingAction != null}
                  className="inline-flex min-h-10 items-center gap-2 rounded-2xl border border-error/25 bg-error/10 px-4 text-sm font-medium text-status-text-error dark:text-status-text-error-dark transition hover:bg-error/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Trash2 className="h-4 w-4" />
                  {t('blackboard.arrangement.actions.remove', 'Remove')}
                </button>
              </>
            )}

            {selection?.kind === 'node' && (
              <>
                <button
                  type="button"
                  onClick={beginMoveMode}
                  className="inline-flex min-h-10 items-center gap-2 rounded-2xl border border-border-light bg-surface-light px-4 text-sm font-medium text-text-primary transition hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-elevated"
                >
                  <Move className="h-4 w-4" />
                  {t('blackboard.arrangement.actions.move', 'Move')}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    void handleDeleteSelection();
                  }}
                  disabled={pendingAction != null}
                  className="inline-flex min-h-10 items-center gap-2 rounded-2xl border border-error/25 bg-error/10 px-4 text-sm font-medium text-status-text-error dark:text-status-text-error-dark transition hover:bg-error/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Trash2 className="h-4 w-4" />
                  {t('blackboard.arrangement.actions.remove', 'Remove')}
                </button>
              </>
            )}
          </div>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(220px,280px)]">
          <div className="space-y-4">
            {selection?.kind === 'empty' && (
              <div className="grid gap-3 sm:grid-cols-3">
                <button
                  type="button"
                  onClick={() => {
                    setAddAgentOpen(true);
                  }}
                  className="flex min-h-[96px] flex-col justify-between rounded-[20px] border border-border-light bg-surface-light p-4 text-left transition hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:bg-surface-dark dark:hover:bg-surface-elevated"
                >
                  <Bot className="h-5 w-5 text-primary dark:text-primary-300" />
                  <div>
                    <div className="text-sm font-medium text-text-primary dark:text-text-inverse">
                      {t('blackboard.arrangement.actions.addAgent', 'Add AI employee')}
                    </div>
                    <div className="mt-1 text-xs leading-5 text-text-secondary dark:text-text-muted">
                      {t(
                        'blackboard.arrangement.actions.addAgentHint',
                        'Bind an agent definition directly onto this hex.'
                      )}
                    </div>
                  </div>
                </button>

                <button
                  type="button"
                  onClick={() => {
                    void handleCreateNode('corridor');
                  }}
                  className="flex min-h-[96px] flex-col justify-between rounded-[20px] border border-border-light bg-surface-light p-4 text-left transition hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:bg-surface-dark dark:hover:bg-surface-elevated"
                >
                  <Route className="h-5 w-5 text-info dark:text-status-text-info-dark" />
                  <div>
                    <div className="text-sm font-medium text-text-primary dark:text-text-inverse">
                      {t('blackboard.arrangement.actions.addCorridor', 'Place corridor')}
                    </div>
                    <div className="mt-1 text-xs leading-5 text-text-secondary dark:text-text-muted">
                      {t(
                        'blackboard.arrangement.actions.addCorridorHint',
                        'Reserve this slot for coordination or routing structure.'
                      )}
                    </div>
                  </div>
                </button>

                <button
                  type="button"
                  onClick={() => {
                    void handleCreateNode('human_seat');
                  }}
                  className="flex min-h-[96px] flex-col justify-between rounded-[20px] border border-border-light bg-surface-light p-4 text-left transition hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:bg-surface-dark dark:hover:bg-surface-elevated"
                >
                  <User className="h-5 w-5 text-warning dark:text-status-text-warning-dark" />
                  <div>
                    <div className="text-sm font-medium text-text-primary dark:text-text-inverse">
                      {t('blackboard.arrangement.actions.addHumanSeat', 'Place human seat')}
                    </div>
                    <div className="mt-1 text-xs leading-5 text-text-secondary dark:text-text-muted">
                      {t(
                        'blackboard.arrangement.actions.addHumanSeatHint',
                        'Mark a human-operated slot for collaboration or review.'
                      )}
                    </div>
                  </div>
                </button>
              </div>
            )}

            {(selection?.kind === 'agent' || selection?.kind === 'node') && (
                <div className="rounded-[20px] border border-border-light bg-surface-light p-4 dark:border-border-dark dark:bg-surface-dark">
                  <div className="grid gap-4 sm:grid-cols-2">
                    <label className="space-y-2 text-sm text-text-primary dark:text-text-secondary">
                      <span className="text-xs uppercase tracking-[0.2em] text-text-muted dark:text-text-muted">
                        {selection.kind === 'agent'
                          ? t('blackboard.arrangement.fields.agentLabel', 'Display label')
                          : t('blackboard.arrangement.fields.nodeLabel', 'Seat label')}
                    </span>
                    <input
                      value={labelDraft}
                        onChange={(event) => {
                          setLabelDraft(event.target.value);
                        }}
                        maxLength={64}
                        className="min-h-11 w-full rounded-2xl border border-border-light bg-surface-muted px-4 text-sm text-text-primary outline-none transition focus:border-primary/60 dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-inverse"
                        placeholder={t(
                          'blackboard.arrangement.fields.labelPlaceholder',
                          'Name this workstation'
                      )}
                    />
                  </label>

                    <div className="space-y-2 text-sm text-text-primary dark:text-text-secondary">
                      <div className="text-xs uppercase tracking-[0.2em] text-text-muted dark:text-text-muted">
                        {t('blackboard.arrangement.fields.accentColor', 'Accent color')}
                      </div>
                      <div className="flex flex-wrap gap-2">
                      {COLOR_SWATCHS.map((swatch) => (
                        <button
                          key={swatch}
                          type="button"
                          aria-label={t('blackboard.arrangement.fields.pickColor', 'Pick color')}
                          onClick={() => {
                            setColorDraft(swatch);
                          }}
                          className={`h-10 w-10 rounded-2xl border transition ${
                            colorDraft === swatch ? 'border-white scale-105' : 'border-white/10 hover:border-white/30'
                          }`}
                          style={{ backgroundColor: swatch }}
                        />
                      ))}
                    </div>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={() => {
                      void handleSaveSelection();
                    }}
                    disabled={pendingAction != null}
                     className="min-h-11 rounded-2xl bg-primary px-5 text-sm font-medium text-white transition hover:bg-primary-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-50"
                   >
                    {pendingAction === 'save-agent' || pendingAction === 'save-node'
                      ? t('common.loading', 'Loading…')
                      : t('blackboard.save', 'Save')}
                  </button>

                  {selection.kind === 'agent' && selectedAgent?.status && (
                      <span className="rounded-full border border-border-light bg-surface-muted px-3 py-2 text-xs text-text-secondary dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-secondary">
                       {t('blackboard.arrangement.fields.status', 'Status')}: {selectedAgent.status}
                     </span>
                   )}
                 </div>
               </div>
             )}

             {selection == null && (
                <div className="rounded-[20px] border border-dashed border-border-separator bg-surface-light p-4 text-sm leading-7 text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
                 {t(
                   'blackboard.arrangement.drawerEmpty',
                   'Use the grid to stage a layout. The action drawer adapts to the selected workstation and keeps destructive actions away from the canvas.'
                )}
              </div>
            )}
          </div>

          <div className="rounded-[20px] border border-border-light bg-surface-light p-4 text-sm leading-7 text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
            <div className="text-xs uppercase tracking-[0.2em] text-text-muted dark:text-text-muted">
              {t('blackboard.arrangement.contextTitle', 'Selection context')}
            </div>
            <div className="mt-3 space-y-3">
              <div className="rounded-2xl border border-border-light bg-surface-muted px-3 py-3 dark:border-border-dark dark:bg-surface-dark-alt">
                {selection?.kind === 'blackboard'
                  ? t(
                      'blackboard.arrangement.context.blackboard',
                      'The central hex opens the full blackboard modal, where discussions, notes, and delivery state stay together.'
                    )
                  : selection?.kind === 'empty'
                    ? t(
                        'blackboard.arrangement.context.empty',
                        'This hex is free. Use it to place a new agent, reserve a human seat, or carve a corridor into the command floor.'
                      )
                    : selection?.kind === 'agent'
                      ? t(
                          'blackboard.arrangement.context.agent',
                          'Agents keep their own workspace binding id, so layout moves stay synced with the workspace roster and real-time events.'
                        )
                      : selection?.kind === 'node'
                        ? t(
                            'blackboard.arrangement.context.node',
                            'Topology nodes are persisted separately from agent bindings, which keeps human seats and corridor structure editable without disturbing execution bindings.'
                          )
                        : t(
                            'blackboard.arrangement.context.none',
                            'No hex selected yet. Pick a slot to inspect its available actions.'
                          )}
              </div>
              <div className="rounded-2xl border border-border-light bg-surface-muted px-3 py-3 dark:border-border-dark dark:bg-surface-dark-alt">
                {moveMode
                  ? t(
                      'blackboard.arrangement.context.move',
                      'A move is armed. Select any free hex outside the center slot to complete it.'
                    )
                  : t(
                      'blackboard.arrangement.context.sync',
                      'Topology changes also stream back in real time. If another collaborator edits this workspace, the grid will reconcile from the event snapshot.'
                    )}
              </div>
            </div>
          </div>
        </div>
      </div>

      <AddAgentModal
        open={addAgentOpen}
        onClose={() => {
          setAddAgentOpen(false);
        }}
        onSubmit={async (data) => {
          await handleAddAgent(data);
          setAddAgentOpen(false);
        }}
        hexCoords={selection?.kind === 'empty' ? { q: selection.q, r: selection.r } : null}
      />
    </section>
  );
}
