import { useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import { hexToPixel, getHexCorners } from '@/components/workspace/hex/useHexLayout';

import {
  coordKey,
  DEFAULT_AGENT_COLOR,
  getNodeAccent,
  getNodeLabel,
  hasEdgeCoordinates,
  HEX_SIZE,
  RESERVED_CENTER_KEY,
} from './arrangementUtils';

import type { TopologyEdge, TopologyNode, WorkspaceAgent } from '@/types/workspace';

import type { MoveMode, SelectionState } from './arrangementUtils';

interface ArrangementHexGridProps {
  gridCells: Array<{ q: number; r: number }>;
  edges: TopologyEdge[];
  agentByCoord: Map<string, WorkspaceAgent>;
  nodeByCoord: Map<string, TopologyNode>;
  selectedHex: { q: number; r: number } | null;
  keyboardCursor: { q: number; r: number };
  moveMode: MoveMode;
  selection: SelectionState | null;
  boardContainerRef: React.RefObject<HTMLDivElement | null>;
  setKeyboardCursor: (v: { q: number; r: number }) => void;
  handleActivateHex: (q: number, r: number) => Promise<void>;
}

export function ArrangementHexGrid({
  gridCells,
  edges,
  agentByCoord,
  nodeByCoord,
  selectedHex,
  keyboardCursor,
  moveMode,
  selection,
  boardContainerRef,
  setKeyboardCursor,
  handleActivateHex,
}: ArrangementHexGridProps) {
  const { t } = useTranslation();

  const edgeElements = useMemo(
    () =>
      edges.filter(hasEdgeCoordinates).map((edge) => {
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
        const isMoveTarget =
          moveMode != null && selection?.kind === 'empty' && selection.q === q && selection.r === r;

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
              className="transition-[fill,stroke,opacity] duration-200 motion-reduce:transition-none"
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
                  {t(
                    'blackboard.arrangement.centerSubtitle',
                    'Open discussion, goals, and execution'
                  )}
                </text>
              </g>
            )}

            {agent && (
              <g>
                <title>{agent.label ?? agent.display_name ?? agent.agent_id}</title>
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
                <title>
                  {getNodeLabel(node, t('blackboard.arrangement.defaults.corridor', 'Corridor'))}
                </title>
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
                  {getNodeLabel(
                    node,
                    t('blackboard.arrangement.defaults.corridor', 'Corridor')
                  ).slice(0, 16)}
                </text>
              </g>
            )}

            {node && node.node_type !== 'corridor' && (
              <g>
                <title>
                  {getNodeLabel(
                    node,
                    node.node_type === 'human_seat'
                      ? t('blackboard.arrangement.defaults.humanSeat', 'Human seat')
                      : t('blackboard.arrangement.defaults.objective', 'Objective')
                  )}
                </title>
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
      boardContainerRef,
      setKeyboardCursor,
    ]
  );

  return (
    <>
      {edgeElements}
      {cellElements}
    </>
  );
}
