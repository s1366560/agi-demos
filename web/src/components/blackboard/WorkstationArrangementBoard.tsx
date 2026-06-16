import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent, WheelEvent as ReactWheelEvent } from 'react';

import { useTranslation } from 'react-i18next';

import { RotateCcw, ZoomIn, ZoomOut } from 'lucide-react';

import { useWorkspaceActions } from '@/stores/workspace';

import { AddAgentModal } from '@/components/workspace/AddAgentModal';
import { hexDistance, generateGrid } from '@/components/workspace/hex/useHexLayout';

import { ArrangementActionDrawer } from './ArrangementActionDrawer';
import { ArrangementHexGrid } from './ArrangementHexGrid';
import {
  coordKey,
  DEFAULT_AGENT_COLOR,
  getGridRadius,
  getNodeLabel,
  hasHex,
  HUMAN_SEAT_COLOR,
  isPlacedAgent,
  isPlacedNode,
  RESERVED_CENTER_KEY,
  resolveColor,
} from './arrangementUtils';
import { HostedProjectionBadge } from './HostedProjectionBadge';
import { KeyboardShortcutsPopover } from './KeyboardShortcutsPopover';
import { useArrangementActions } from './useArrangementActions';
import { useArrangementKeyboard } from './useArrangementKeyboard';

import type { TopologyNode, WorkspaceAgent } from '@/types/workspace';

import type {
  MoveMode,
  SelectionState,
  ViewMode,
  WorkstationArrangementBoardProps,
} from './arrangementUtils';

const HexCanvas3D = lazy(() =>
  import('@/components/workspace/hex3d/HexCanvas3D').then((module) => ({
    default: module.HexCanvas3D,
  }))
);

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
    selection?.kind === 'agent'
      ? (agents.find((agent) => agent.id === selection.agentId) ?? null)
      : null;
  const selectedNode =
    selection?.kind === 'node'
      ? (nodes.find((node) => node.id === selection.nodeId) ?? null)
      : null;

  const selectedHex = useMemo(() => {
    if (!selection) {
      return null;
    }
    if (selection.kind === 'empty' || selection.kind === 'blackboard') {
      return { q: selection.q, r: selection.r };
    }
    if (
      selection.kind === 'agent' &&
      selectedAgent &&
      hasHex(selectedAgent.hex_q) &&
      hasHex(selectedAgent.hex_r)
    ) {
      return { q: selectedAgent.hex_q, r: selectedAgent.hex_r };
    }
    if (
      selection.kind === 'node' &&
      selectedNode &&
      hasHex(selectedNode.hex_q) &&
      hasHex(selectedNode.hex_r)
    ) {
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

  const actions = useArrangementActions({
    tenantId,
    projectId,
    workspaceId,
    agents,
    nodes,
    selection,
    moveMode,
    selectedAgent,
    selectedNode,
    agentByCoord,
    nodeByCoord,
    setSelection,
    setMoveMode,
    bindAgent,
    updateAgentBinding,
    unbindAgent,
    moveAgent,
    createTopologyNode,
    updateTopologyNode,
    deleteTopologyNode,
    onOpenBlackboard,
  });

  const handleActivateHex = useCallback(
    async (q: number, r: number) => {
      setKeyboardCursor({ q, r });
      await actions.handleActivateHex(q, r);
    },
    [actions]
  );

  useEffect(() => {
    if (selection?.kind === 'agent' && selectedAgent == null) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- clear stale selection when agent removed
      setSelection(null);
      setMoveMode(null);
    }
  }, [selectedAgent, selection]);

  useEffect(() => {
    if (selection?.kind === 'node' && selectedNode == null) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- clear stale selection when node removed
      setSelection(null);
      setMoveMode(null);
    }
  }, [selectedNode, selection]);

  useEffect(() => {
    if (!selection) {
      actions.setLabelDraft('');
      actions.setColorDraft(DEFAULT_AGENT_COLOR);
      return;
    }
    if (selection.kind === 'agent' && selectedAgent) {
      actions.setLabelDraft(selectedAgent.label ?? selectedAgent.display_name ?? '');
      actions.setColorDraft(selectedAgent.theme_color ?? DEFAULT_AGENT_COLOR);
      return;
    }
    if (selection.kind === 'node' && selectedNode) {
      actions.setLabelDraft(selectedNode.title);
      actions.setColorDraft(resolveColor(selectedNode.data.color, HUMAN_SEAT_COLOR));
      return;
    }
    actions.setLabelDraft('');
    actions.setColorDraft(DEFAULT_AGENT_COLOR);
  }, [actions, selectedAgent, selectedNode, selection]);

  useEffect(() => {
    if (selectedHex) {
      selectHex(selectedHex.q, selectedHex.r);
      return;
    }
    clearSelectedHex();
  }, [clearSelectedHex, selectHex, selectedHex]);

  useEffect(() => {
    if (selectedHex) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- sync cursor with hex selection
      setKeyboardCursor({ q: selectedHex.q, r: selectedHex.r });
    }
  }, [selectedHex]);

  useEffect(() => {
    if (!isKeyboardGridActive) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reset focus when keyboard grid deactivates
      setIsBoardFocused(false);
    }
  }, [isKeyboardGridActive]);

  useEffect(() => {
    if (hexDistance(0, 0, keyboardCursor.q, keyboardCursor.r) > gridRadius) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- clamp cursor within grid bounds
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

  const handleBoardKeyDown = useArrangementKeyboard({
    selection,
    viewMode,
    keyboardCursor,
    gridRadius,
    agentByCoord,
    nodeByCoord,
    setSelection,
    setMoveMode,
    setViewMode,
    setZoom,
    setKeyboardCursor,
    setAddAgentOpen: actions.setAddAgentOpen,
    resetView,
    nudgePan,
    handleActivateHex,
    handleCreateNode: actions.handleCreateNode,
    handleDeleteSelection: actions.handleDeleteSelection,
    beginMoveMode: actions.beginMoveMode,
  });

  const handleWheel = useCallback((event: ReactWheelEvent<SVGSVGElement>) => {
    event.preventDefault();
    const delta = event.deltaY > 0 ? -0.1 : 0.1;
    setZoom((current) => Math.max(0.55, Math.min(2.2, current + delta)));
  }, []);

  const handlePointerDown = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>) => {
      if (event.target instanceof Element && event.target.closest('[data-hex-cell="true"]')) {
        return;
      }
      boardContainerRef.current?.focus();
      setPanning(true);
      setPanAnchor({ x: event.clientX - pan.x, y: event.clientY - pan.y });
    },
    [pan.x, pan.y]
  );

  const handlePointerMove = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>) => {
      if (!panning) {
        return;
      }
      setPan({ x: event.clientX - panAnchor.x, y: event.clientY - panAnchor.y });
    },
    [panAnchor.x, panAnchor.y, panning]
  );

  const svgTransform = useMemo(
    () =>
      [
        'translate(',
        pan.x.toString(),
        ', ',
        pan.y.toString(),
        ') scale(',
        zoom.toString(),
        ')',
      ].join(''),
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
    <section className="flex h-full flex-col rounded-lg border border-border-light bg-surface-light p-4 shadow-sm transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:bg-surface-dark sm:p-5">
      <HostedProjectionBadge
        labelKey="blackboard.arrangementSurfaceHint"
        fallbackLabel="workspace arrangement projection"
      />

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-b border-border-light pb-4 dark:border-border-dark">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold tracking-tight text-text-primary dark:text-text-inverse">
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

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-text-secondary dark:text-text-muted">
            {t(
              'blackboard.arrangement.inlineStats',
              '{{agents}} Agents · {{seats}} Human · {{corridors}} Corridors · {{done}}/{{total}} Tasks',
              {
                agents: agents.length,
                seats: summary.humanSeats,
                corridors: summary.corridors,
                done: summary.completedTasks,
                total: tasks.length,
              }
            )}
          </span>

          <span className="h-4 w-px bg-border-light dark:bg-border-dark" />

          <div className="inline-flex rounded-lg border border-border-light bg-surface-muted p-1 dark:border-border-dark dark:bg-surface-dark-alt">
            {(['2d', '3d'] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => {
                  setViewMode(mode);
                }}
                className={`min-h-8 rounded-[10px] px-3 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 ${
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

          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => {
                setZoom((current) => Math.max(0.55, current - 0.15));
              }}
              disabled={viewMode !== '2d'}
              aria-label={t('blackboard.arrangement.zoomOut', 'Zoom out')}
              title={t('blackboard.arrangement.zoomOut', 'Zoom out')}
              className="flex h-8 w-8 items-center justify-center rounded-md border border-border-light bg-surface-muted text-text-secondary transition-colors duration-150 hover:bg-surface-light focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-secondary dark:hover:bg-surface-elevated"
            >
              <ZoomOut className="h-3.5 w-3.5" />
            </button>

            <button
              type="button"
              onClick={() => {
                setZoom((current) => Math.min(2.2, current + 0.15));
              }}
              disabled={viewMode !== '2d'}
              aria-label={t('blackboard.arrangement.zoomIn', 'Zoom in')}
              title={t('blackboard.arrangement.zoomIn', 'Zoom in')}
              className="flex h-8 w-8 items-center justify-center rounded-md border border-border-light bg-surface-muted text-text-secondary transition-colors duration-150 hover:bg-surface-light focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-secondary dark:hover:bg-surface-elevated"
            >
              <ZoomIn className="h-3.5 w-3.5" />
            </button>

            <button
              type="button"
              onClick={resetView}
              className="flex h-8 w-8 items-center justify-center rounded-md border border-border-light bg-surface-muted text-text-secondary transition-colors duration-150 hover:bg-surface-light focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-secondary dark:hover:bg-surface-elevated"
              title={t('blackboard.arrangement.resetView', 'Reset view')}
            >
              <RotateCcw className="h-3.5 w-3.5" />
              <span className="sr-only">{t('blackboard.arrangement.resetView', 'Reset view')}</span>
            </button>
          </div>

          <span className="h-4 w-px bg-border-light dark:bg-border-dark" />

          <KeyboardShortcutsPopover moveMode={moveMode} />
        </div>
      </div>

      <div className="mt-3 flex-1 min-h-0">
        <div className="flex flex-col h-full overflow-hidden rounded-[24px] border border-border-light bg-surface-light dark:border-border-dark dark:bg-background-dark">
          {!isKeyboardGridActive && (
            <p className="text-xs text-text-secondary dark:text-text-muted px-4 py-2">
              {t(
                'blackboard.arrangement.threeDPreviewNote',
                '3D view is preview only. Use pointer controls here, or switch back to 2D for keyboard editing.'
              )}
            </p>
          )}

          <div className="relative flex-1 min-h-[280px] w-full">
            {isBoardFocused && isKeyboardGridActive && (
              <div className="absolute bottom-4 left-4 z-10 pointer-events-none">
                <span className="max-w-full truncate rounded-full border border-info/25 bg-info/10 px-3 py-1 text-[11px] font-medium text-status-text-info dark:text-status-text-info-dark sm:max-w-[28rem]">
                  {keyboardCursorSummary}
                </span>
              </div>
            )}
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
                aria-label={t(
                  'blackboard.arrangement.ariaLabel',
                  'Interactive workstation arrangement grid'
                )}
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
                  <rect
                    x={-760}
                    y={-560}
                    width={1520}
                    height={1120}
                    fill="url(#blackboard-grid-glow)"
                  />
                  <g transform={svgTransform}>
                    <ArrangementHexGrid
                      gridCells={gridCells}
                      edges={edges}
                      agentByCoord={agentByCoord}
                      nodeByCoord={nodeByCoord}
                      selectedHex={selectedHex}
                      keyboardCursor={keyboardCursor}
                      moveMode={moveMode}
                      selection={selection}
                      boardContainerRef={boardContainerRef}
                      setKeyboardCursor={setKeyboardCursor}
                      handleActivateHex={handleActivateHex}
                    />
                  </g>
                </svg>
              </div>
            ) : (
              <div
                tabIndex={-1}
                role="group"
                aria-label={t(
                  'blackboard.arrangement.threeDAriaLabel',
                  'Three-dimensional workstation arrangement'
                )}
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
              <div className="pointer-events-none absolute inset-x-4 bottom-4 rounded-lg border border-border-light/80 bg-surface-light/95 px-4 py-3 text-sm text-text-secondary shadow-md dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-secondary">
                {t(
                  'blackboard.arrangement.emptySelectionHint',
                  'Start by selecting an empty hex, an AI employee, or the center board.'
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      <ArrangementActionDrawer
        selection={selection}
        selectedAgent={selectedAgent}
        selectedNode={selectedNode}
        selectedHex={selectedHex}
        agentWorkspacePath={agentWorkspacePath}
        pendingAction={actions.pendingAction}
        labelDraft={actions.labelDraft}
        colorDraft={actions.colorDraft}
        setLabelDraft={actions.setLabelDraft}
        setColorDraft={actions.setColorDraft}
        setAddAgentOpen={actions.setAddAgentOpen}
        onOpenBlackboard={onOpenBlackboard}
        handleCreateNode={actions.handleCreateNode}
        handleSaveSelection={actions.handleSaveSelection}
        handleDeleteSelection={actions.handleDeleteSelection}
        beginMoveMode={actions.beginMoveMode}
        moveMode={moveMode}
      />

      <AddAgentModal
        open={actions.addAgentOpen}
        projectId={projectId}
        onClose={() => {
          actions.setAddAgentOpen(false);
        }}
        onSubmit={async (data) => {
          await actions.handleAddAgent(data);
          actions.setAddAgentOpen(false);
        }}
        hexCoords={selection?.kind === 'empty' ? { q: selection.q, r: selection.r } : null}
      />
    </section>
  );
}
