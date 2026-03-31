import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent, WheelEvent as ReactWheelEvent } from 'react';

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
import { HexCanvas3D } from '@/components/workspace/hex3d/HexCanvas3D';

import { getErrorMessage } from '@/types/common';
import type { TopologyEdge, TopologyNode, WorkspaceAgent, WorkspaceTask } from '@/types/workspace';

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
const DEFAULT_AGENT_COLOR = '#1e3fae';
const HUMAN_SEAT_COLOR = '#f59e0b';
const MAX_LAYOUT_RADIUS = 24;
const MAX_RENDER_GRID_RADIUS = 26;
const COLOR_SWATCHS = ['#1e3fae', '#2563eb', '#7c3aed', '#0f766e', '#d97706', '#dc2626'];

const KEYBOARD_HINTS = [
  ['W/A/S/D', 'blackboard.arrangement.shortcuts.pan'],
  ['+ / -', 'blackboard.arrangement.shortcuts.zoom'],
  ['0', 'blackboard.arrangement.shortcuts.reset'],
  ['A / C / H', 'blackboard.arrangement.shortcuts.place'],
  ['M / Del', 'blackboard.arrangement.shortcuts.edit'],
  ['2 / 3 / Esc', 'blackboard.arrangement.shortcuts.mode'],
] as const;

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
    return '#8b5cf6';
  }
  return '#06b6d4';
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

  const svgRef = useRef<SVGSVGElement | null>(null);

  const gridRadius = useMemo(() => getGridRadius(agents, nodes), [agents, nodes]);
  const gridCells = useMemo(() => generateGrid(gridRadius), [gridRadius]);

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
    async (nodeType: TopologyNode['node_type']) => {
      if (selection?.kind !== 'empty') {
        return;
      }
      const logicalPosition = hexToPixel(selection.q, selection.r, 1);
      const defaultTitle =
        nodeType === 'human_seat'
          ? t('blackboard.arrangement.defaults.humanSeat', 'Human seat')
          : t('blackboard.arrangement.defaults.corridor', 'Corridor');

      setPendingAction(`create-${nodeType}`);
      try {
        const createdNode = await createTopologyNode(workspaceId, {
          node_type: nodeType,
          title: defaultTitle,
          hex_q: selection.q,
          hex_r: selection.r,
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

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
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

      if (event.key.toLowerCase() === 'w' || event.key === 'ArrowUp') {
        event.preventDefault();
        nudgePan(0, 28);
        return;
      }

      if (event.key.toLowerCase() === 's' || event.key === 'ArrowDown') {
        event.preventDefault();
        nudgePan(0, -28);
        return;
      }

      if (event.key.toLowerCase() === 'a' || event.key === 'ArrowLeft') {
        if (selection?.kind === 'empty') {
          event.preventDefault();
          setAddAgentOpen(true);
          return;
        }
        event.preventDefault();
        nudgePan(28, 0);
        return;
      }

      if (event.key.toLowerCase() === 'd' || event.key === 'ArrowRight') {
        event.preventDefault();
        nudgePan(-28, 0);
        return;
      }

      if (selection?.kind === 'empty' && event.key.toLowerCase() === 'c') {
        event.preventDefault();
        void handleCreateNode('corridor');
        return;
      }

      if (selection?.kind === 'empty' && event.key.toLowerCase() === 'h') {
        event.preventDefault();
        void handleCreateNode('human_seat');
        return;
      }

      if ((selection?.kind === 'agent' || selection?.kind === 'node') && event.key.toLowerCase() === 'm') {
        event.preventDefault();
        beginMoveMode();
        return;
      }

      if ((selection?.kind === 'agent' || selection?.kind === 'node') && (event.key === 'Delete' || event.key === 'Backspace')) {
        event.preventDefault();
        void handleDeleteSelection();
        return;
      }

      if (selection?.kind === 'blackboard' && event.key === 'Enter') {
        event.preventDefault();
        onOpenBlackboard();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [
    beginMoveMode,
    handleCreateNode,
    handleDeleteSelection,
    nudgePan,
    onOpenBlackboard,
    resetView,
    selection,
  ]);

  const handleWheel = useCallback((event: ReactWheelEvent<SVGSVGElement>) => {
    event.preventDefault();
    const delta = event.deltaY > 0 ? -0.1 : 0.1;
    setZoom((current) => Math.max(0.55, Math.min(2.2, current + delta)));
  }, []);

  const handlePointerDown = useCallback((event: ReactPointerEvent<SVGSVGElement>) => {
    if (event.target !== event.currentTarget) {
      return;
    }
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
                stroke="rgba(34, 197, 94, 0.28)"
                strokeWidth={10}
                strokeLinecap="round"
              />
              <line
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                stroke="rgba(125, 211, 252, 0.9)"
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
        const isMoveTarget = moveMode != null && selection?.kind === 'empty' && selection.q === q && selection.r === r;

        return (
          <g
            key={key}
            role="button"
            tabIndex={0}
            onClick={(event) => {
              event.stopPropagation();
              void handleActivateHex(q, r);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                void handleActivateHex(q, r);
              }
            }}
          >
            <polygon
              points={points}
              fill={
                isCenter
                  ? 'rgba(99, 102, 241, 0.18)'
                  : isSelected
                    ? 'rgba(59, 130, 246, 0.14)'
                    : agent || node
                      ? 'rgba(255, 255, 255, 0.04)'
                      : 'transparent'
              }
              stroke={
                isCenter
                  ? 'rgba(167, 139, 250, 0.78)'
                  : isSelected
                    ? 'rgba(96, 165, 250, 0.95)'
                    : 'rgba(148, 163, 184, 0.2)'
              }
              strokeWidth={isCenter ? 3 : isSelected ? 2.5 : 1}
              strokeDasharray={isMoveTarget ? '10 6' : undefined}
              className="transition-all duration-200 motion-reduce:transition-none"
            />

            {isCenter && (
              <g>
                <text
                  x={center.x}
                  y={center.y - 8}
                  textAnchor="middle"
                  className="fill-violet-100 text-[16px] font-semibold"
                >
                  {t('blackboard.arrangement.centerTitle', 'Central blackboard')}
                </text>
                <text
                  x={center.x}
                  y={center.y + 18}
                  textAnchor="middle"
                  className="fill-zinc-400 text-[12px]"
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
                  className="fill-zinc-100 text-[12px] font-medium"
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
                  stroke="rgba(34, 211, 238, 0.95)"
                  strokeWidth={3}
                  strokeLinecap="round"
                />
                <line
                  x1={center.x}
                  y1={center.y - 18}
                  x2={center.x}
                  y2={center.y + 18}
                  stroke="rgba(34, 211, 238, 0.4)"
                  strokeWidth={3}
                  strokeLinecap="round"
                />
                <text
                  x={center.x}
                  y={center.y + 30}
                  textAnchor="middle"
                  className="fill-cyan-100 text-[11px] font-medium"
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
                  className="fill-zinc-100 text-[11px] font-medium"
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

  return (
    <section className="rounded-[28px] border border-white/8 bg-[radial-gradient(circle_at_top,_rgba(59,130,246,0.16),_transparent_38%),linear-gradient(180deg,_rgba(8,11,18,0.98),_rgba(3,6,12,0.98))] p-4 shadow-[0_24px_70px_rgba(2,6,23,0.45)] sm:p-5">
      <div className="flex flex-col gap-4 border-b border-white/8 pb-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-2">
          <div className="text-[11px] uppercase tracking-[0.28em] text-sky-300/70">
            {t('blackboard.arrangement.eyebrow', 'Workstation arrangement')}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-2xl font-semibold text-zinc-50">{workspaceName}</h2>
            <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-xs font-medium text-emerald-200">
              {t('blackboard.arrangement.syncState', 'Live topology sync')}
            </span>
            {moveMode && (
              <span className="rounded-full border border-amber-400/20 bg-amber-400/10 px-3 py-1 text-xs font-medium text-amber-100">
                {t('blackboard.arrangement.moveMode', 'Move mode: click a free hex')}
              </span>
            )}
          </div>
          <p className="max-w-3xl text-sm leading-7 text-zinc-400">
            {t(
              'blackboard.arrangement.description',
              'Place AI employees, human seats, and corridor nodes on a shared command grid, then jump straight into the central blackboard when coordination needs more depth.'
            )}
          </p>
        </div>

        <div className="flex flex-col gap-3 lg:min-w-[320px] lg:items-end">
          <div className="flex flex-wrap justify-end gap-2">
            <span className="rounded-2xl border border-white/8 bg-white/[0.04] px-3 py-2 text-xs text-zinc-300">
              {t('blackboard.arrangement.metrics.agents', '{{count}} agents', { count: agents.length })}
            </span>
            <span className="rounded-2xl border border-white/8 bg-white/[0.04] px-3 py-2 text-xs text-zinc-300">
              {t('blackboard.arrangement.metrics.seats', '{{count}} human seats', {
                count: summary.humanSeats,
              })}
            </span>
            <span className="rounded-2xl border border-white/8 bg-white/[0.04] px-3 py-2 text-xs text-zinc-300">
              {t('blackboard.arrangement.metrics.corridors', '{{count}} corridors', {
                count: summary.corridors,
              })}
            </span>
            <span className="rounded-2xl border border-white/8 bg-white/[0.04] px-3 py-2 text-xs text-zinc-300">
              {t('blackboard.arrangement.metrics.tasks', '{{done}} / {{total}} tasks done', {
                done: summary.completedTasks,
                total: tasks.length,
              })}
            </span>
          </div>

          <div className="flex flex-wrap items-center justify-end gap-2">
            <div className="inline-flex rounded-2xl border border-white/8 bg-white/[0.04] p-1">
              {(['2d', '3d'] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => {
                    setViewMode(mode);
                  }}
                  className={`min-h-10 rounded-[14px] px-4 text-sm font-medium transition ${
                    viewMode === mode
                      ? 'bg-sky-500 text-white shadow-[0_10px_30px_rgba(14,165,233,0.28)]'
                      : 'text-zinc-400 hover:bg-white/[0.05] hover:text-zinc-100'
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
              className="inline-flex min-h-10 items-center gap-2 rounded-2xl border border-white/8 bg-white/[0.04] px-3 text-sm text-zinc-200 transition hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-40"
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
              className="inline-flex min-h-10 items-center gap-2 rounded-2xl border border-white/8 bg-white/[0.04] px-3 text-sm text-zinc-200 transition hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ZoomIn className="h-4 w-4" />
              <Plus className="h-3 w-3" />
            </button>

            <button
              type="button"
              onClick={resetView}
              className="inline-flex min-h-10 items-center gap-2 rounded-2xl border border-white/8 bg-white/[0.04] px-4 text-sm text-zinc-200 transition hover:bg-white/[0.08]"
            >
              <RotateCcw className="h-4 w-4" />
              {t('blackboard.arrangement.resetView', 'Reset view')}
            </button>
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_280px]">
        <div className="overflow-hidden rounded-[24px] border border-white/8 bg-[#04070d]">
          <div className="flex items-center justify-between border-b border-white/8 px-4 py-3">
            <div>
              <div className="text-sm font-medium text-zinc-100">
                {t('blackboard.arrangement.canvasTitle', 'Command grid')}
              </div>
              <div className="text-xs text-zinc-500">
                {t(
                  'blackboard.arrangement.canvasSubtitle',
                  'Select a hex to stage a new seat, update an agent, or drill into the blackboard.'
                )}
              </div>
            </div>
            <button
              type="button"
              onClick={onOpenBlackboard}
              className="inline-flex min-h-10 items-center gap-2 rounded-2xl border border-violet-400/20 bg-violet-500/12 px-4 text-sm font-medium text-violet-100 transition hover:bg-violet-500/20"
            >
              {t('blackboard.openBoard', 'Open central blackboard')}
            </button>
          </div>

          <div className="relative h-[620px] w-full">
            {viewMode === '2d' ? (
              <svg
                ref={svgRef}
                className="h-full w-full touch-none"
                role="img"
                aria-label={t('blackboard.arrangement.ariaLabel', 'Interactive workstation arrangement grid')}
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
                    <stop offset="0%" stopColor="rgba(56, 189, 248, 0.18)" />
                    <stop offset="100%" stopColor="rgba(56, 189, 248, 0)" />
                  </radialGradient>
                </defs>
                <rect x={-760} y={-560} width={1520} height={1120} fill="url(#blackboard-grid-glow)" />
                <g transform={svgTransform}>
                  {edgeElements}
                  {cellElements}
                </g>
              </svg>
            ) : (
              <HexCanvas3D
                agents={placedAgents}
                nodes={placedNodes}
                edges={edges}
                gridRadius={gridRadius}
                onSelectHex={(q, r) => {
                  void handleActivateHex(q, r);
                }}
              />
            )}

            {selection == null && (
              <div className="pointer-events-none absolute inset-x-4 bottom-4 rounded-2xl border border-white/8 bg-black/35 px-4 py-3 text-sm text-zinc-300 backdrop-blur">
                {t(
                  'blackboard.arrangement.emptySelectionHint',
                  'Start by selecting an empty hex, an AI employee, or the center board.'
                )}
              </div>
            )}
          </div>
        </div>

        <aside className="hidden rounded-[24px] border border-white/8 bg-white/[0.03] p-4 xl:block">
          <div className="flex items-center gap-2 text-sm font-medium text-zinc-100">
            <Keyboard className="h-4 w-4 text-sky-300" />
            {t('blackboard.arrangement.shortcutTitle', 'Keyboard map')}
          </div>
          <div className="mt-4 space-y-2">
            {KEYBOARD_HINTS.map(([keys, labelKey]) => (
              <div
                key={keys}
                className="flex items-center justify-between rounded-2xl border border-white/8 bg-black/20 px-3 py-2 text-xs text-zinc-300"
              >
                <span>{t(labelKey, labelKey)}</span>
                <kbd className="rounded-lg border border-white/10 bg-white/[0.06] px-2 py-1 font-mono text-[11px] text-zinc-100">
                  {keys}
                </kbd>
              </div>
            ))}
          </div>

          <div className="mt-4 rounded-2xl border border-white/8 bg-black/20 p-3 text-xs leading-6 text-zinc-400">
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

      <div className="mt-4 rounded-[24px] border border-white/8 bg-white/[0.03] p-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="text-sm font-medium text-zinc-100">
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
            <div className="mt-1 text-xs text-zinc-500">
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
                className="inline-flex min-h-10 items-center rounded-2xl border border-violet-400/20 bg-violet-500/12 px-4 text-sm font-medium text-violet-100 transition hover:bg-violet-500/20"
              >
                {t('blackboard.openBoard', 'Open central blackboard')}
              </button>
            )}

            {selection?.kind === 'agent' && (
              <>
                <Link
                  to={agentWorkspacePath}
                  className="inline-flex min-h-10 items-center gap-2 rounded-2xl border border-white/8 bg-white/[0.04] px-4 text-sm font-medium text-zinc-100 transition hover:bg-white/[0.08]"
                >
                  <ExternalLink className="h-4 w-4" />
                  {t('blackboard.arrangement.openWorkspace', 'Open workspace')}
                </Link>
                <button
                  type="button"
                  onClick={beginMoveMode}
                  className="inline-flex min-h-10 items-center gap-2 rounded-2xl border border-white/8 bg-white/[0.04] px-4 text-sm font-medium text-zinc-100 transition hover:bg-white/[0.08]"
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
                  className="inline-flex min-h-10 items-center gap-2 rounded-2xl border border-rose-400/20 bg-rose-500/12 px-4 text-sm font-medium text-rose-100 transition hover:bg-rose-500/18 disabled:cursor-not-allowed disabled:opacity-50"
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
                  className="inline-flex min-h-10 items-center gap-2 rounded-2xl border border-white/8 bg-white/[0.04] px-4 text-sm font-medium text-zinc-100 transition hover:bg-white/[0.08]"
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
                  className="inline-flex min-h-10 items-center gap-2 rounded-2xl border border-rose-400/20 bg-rose-500/12 px-4 text-sm font-medium text-rose-100 transition hover:bg-rose-500/18 disabled:cursor-not-allowed disabled:opacity-50"
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
                  className="flex min-h-[96px] flex-col justify-between rounded-[20px] border border-white/8 bg-white/[0.04] p-4 text-left transition hover:bg-white/[0.08]"
                >
                  <Bot className="h-5 w-5 text-sky-300" />
                  <div>
                    <div className="text-sm font-medium text-zinc-50">
                      {t('blackboard.arrangement.actions.addAgent', 'Add AI employee')}
                    </div>
                    <div className="mt-1 text-xs leading-5 text-zinc-500">
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
                  className="flex min-h-[96px] flex-col justify-between rounded-[20px] border border-white/8 bg-white/[0.04] p-4 text-left transition hover:bg-white/[0.08]"
                >
                  <Route className="h-5 w-5 text-cyan-300" />
                  <div>
                    <div className="text-sm font-medium text-zinc-50">
                      {t('blackboard.arrangement.actions.addCorridor', 'Place corridor')}
                    </div>
                    <div className="mt-1 text-xs leading-5 text-zinc-500">
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
                  className="flex min-h-[96px] flex-col justify-between rounded-[20px] border border-white/8 bg-white/[0.04] p-4 text-left transition hover:bg-white/[0.08]"
                >
                  <User className="h-5 w-5 text-amber-300" />
                  <div>
                    <div className="text-sm font-medium text-zinc-50">
                      {t('blackboard.arrangement.actions.addHumanSeat', 'Place human seat')}
                    </div>
                    <div className="mt-1 text-xs leading-5 text-zinc-500">
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
              <div className="rounded-[20px] border border-white/8 bg-black/15 p-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="space-y-2 text-sm text-zinc-200">
                    <span className="text-xs uppercase tracking-[0.2em] text-zinc-500">
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
                      className="min-h-11 w-full rounded-2xl border border-white/10 bg-white/[0.04] px-4 text-sm text-zinc-100 outline-none transition focus:border-sky-400/60"
                      placeholder={t(
                        'blackboard.arrangement.fields.labelPlaceholder',
                        'Name this workstation'
                      )}
                    />
                  </label>

                  <div className="space-y-2 text-sm text-zinc-200">
                    <div className="text-xs uppercase tracking-[0.2em] text-zinc-500">
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
                    className="min-h-11 rounded-2xl bg-sky-500 px-5 text-sm font-medium text-white transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {pendingAction === 'save-agent' || pendingAction === 'save-node'
                      ? t('common.loading', 'Loading…')
                      : t('blackboard.save', 'Save')}
                  </button>

                  {selection.kind === 'agent' && selectedAgent?.status && (
                    <span className="rounded-full border border-white/8 bg-white/[0.04] px-3 py-2 text-xs text-zinc-300">
                      {t('blackboard.arrangement.fields.status', 'Status')}: {selectedAgent.status}
                    </span>
                  )}
                </div>
              </div>
            )}

            {selection == null && (
              <div className="rounded-[20px] border border-dashed border-white/10 bg-black/15 p-4 text-sm leading-7 text-zinc-400">
                {t(
                  'blackboard.arrangement.drawerEmpty',
                  'Use the grid to stage a layout. The action drawer adapts to the selected workstation and keeps destructive actions away from the canvas.'
                )}
              </div>
            )}
          </div>

          <div className="rounded-[20px] border border-white/8 bg-black/15 p-4 text-sm leading-7 text-zinc-400">
            <div className="text-xs uppercase tracking-[0.2em] text-zinc-500">
              {t('blackboard.arrangement.contextTitle', 'Selection context')}
            </div>
            <div className="mt-3 space-y-3">
              <div className="rounded-2xl border border-white/8 bg-white/[0.03] px-3 py-3">
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
              <div className="rounded-2xl border border-white/8 bg-white/[0.03] px-3 py-3">
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
