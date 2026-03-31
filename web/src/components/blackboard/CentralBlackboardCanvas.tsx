import type React from 'react';
import { Component, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import {
  AlertTriangle,
  Bot,
  ChevronRight,
  ClipboardCheck,
  MessageSquareText,
  Users,
} from 'lucide-react';

import { generateGrid, getHexCorners, hexToPixel } from '@/components/workspace/hex/useHexLayout';

import { buildBlackboardStats, buildCanvasActors, buildCanvasLinks } from './blackboardUtils';

import type {
  BlackboardPost,
  TopologyEdge,
  TopologyNode,
  WorkspaceAgent,
  WorkspaceTask,
} from '@/types/workspace';

const GRID_RADIUS = 7;
const GRID_HEX_SIZE = 88;
const BOARD_NODE_SIZE = 122;
const OUTER_NODE_SIZE = 90;

function truncateLabel(label: string, maxLength: number): string {
  return label.length > maxLength ? `${label.slice(0, maxLength - 1)}…` : label;
}

function toPolygonPoints(cx: number, cy: number, size: number): string {
  return getHexCorners(cx, cy, size)
    .map((corner) => `${String(corner.x)},${String(corner.y)}`)
    .join(' ');
}

function getNodePalette(kind: 'blackboard' | 'agent' | 'human'): {
  fill: string;
  stroke: string;
  glow: string;
  text: string;
  muted: string;
} {
  if (kind === 'agent') {
    return {
      fill: 'var(--color-success-bg-dark)',
      stroke: 'var(--color-success)',
      glow: 'var(--color-success)',
      text: 'var(--color-text-inverse)',
      muted: 'var(--color-status-text-success-dark)',
    };
  }

  if (kind === 'human') {
    return {
      fill: 'var(--color-warning-bg-dark)',
      stroke: 'var(--color-warning)',
      glow: 'var(--color-warning-dark)',
      text: 'var(--color-text-inverse)',
      muted: 'var(--color-status-text-warning-dark)',
    };
  }

  return {
    fill: 'var(--color-primary-900)',
    stroke: 'var(--color-primary-light)',
    glow: 'var(--color-primary-glow)',
    text: 'var(--color-text-inverse)',
    muted: 'var(--color-primary-200)',
  };
}

interface ErrorBoundaryProps {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

class CanvasErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  override render(): React.ReactNode {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <div className="flex min-h-[320px] items-center justify-center rounded-3xl border border-border-light bg-surface-muted p-8 text-center dark:border-border-dark dark:bg-background-dark">
            <div>
              <p className="text-sm text-text-secondary dark:text-text-muted">
                Canvas rendering failed. Please refresh the page.
              </p>
            </div>
          </div>
        )
      );
    }
    return this.props.children;
  }
}

export interface CentralBlackboardCanvasProps {
  workspaceName: string;
  tasks: WorkspaceTask[];
  posts: BlackboardPost[];
  agents: WorkspaceAgent[];
  topologyNodes: TopologyNode[];
  topologyEdges: TopologyEdge[];
  onOpenBlackboard: () => void;
}

export function CentralBlackboardCanvas({
  workspaceName,
  tasks,
  posts,
  agents,
  topologyNodes,
  topologyEdges,
  onOpenBlackboard,
}: CentralBlackboardCanvasProps) {
  const { t } = useTranslation();

  const stats = useMemo(
    () => buildBlackboardStats(tasks, posts, agents, topologyNodes),
    [agents, posts, tasks, topologyNodes]
  );

  const actors = useMemo(() => buildCanvasActors(agents, topologyNodes), [agents, topologyNodes]);

  const topologyLinks = useMemo(
    () => buildCanvasLinks(actors, topologyEdges),
    [actors, topologyEdges]
  );

  const gridCells = useMemo(() => generateGrid(GRID_RADIUS), []);

  const pixelActors = useMemo(
    () =>
      actors.map((actor) => ({
        ...actor,
        ...hexToPixel(actor.q, actor.r, GRID_HEX_SIZE),
      })),
    [actors]
  );

  const pixelLinks = useMemo(
    () =>
      topologyLinks.map((link) => ({
        ...link,
        fromPixel: hexToPixel(link.from.q, link.from.r, GRID_HEX_SIZE),
        toPixel: hexToPixel(link.to.q, link.to.r, GRID_HEX_SIZE),
      })),
    [topologyLinks]
  );

  const pixelGrid = useMemo(
    () =>
      gridCells.map((cell) => ({
        ...cell,
        ...hexToPixel(cell.q, cell.r, GRID_HEX_SIZE),
      })),
    [gridCells]
  );

  const viewBox = useMemo(() => {
    const allPoints = [
      ...pixelGrid.map((cell) => ({ x: cell.x, y: cell.y })),
      ...pixelActors.map((actor) => ({ x: actor.x, y: actor.y })),
      { x: 0, y: 0 },
    ];

    const xs = allPoints.map((point) => point.x);
    const ys = allPoints.map((point) => point.y);
    const minX = Math.min(...xs) - 240;
    const maxX = Math.max(...xs) + 240;
    const minY = Math.min(...ys) - 220;
    const maxY = Math.max(...ys) + 220;

    return `${String(minX)} ${String(minY)} ${String(maxX - minX)} ${String(maxY - minY)}`;
  }, [pixelActors, pixelGrid]);

  const statCards = [
    {
      key: 'tasks',
      label: t('blackboard.metrics.tasks', 'Tasks'),
      value: `${String(stats.completedTasks)}/${String(stats.totalTasks || 0)}`,
      helper: t('blackboard.metrics.completed', 'completed'),
      icon: ClipboardCheck,
    },
    {
      key: 'discussions',
      label: t('blackboard.metrics.discussions', 'Discussions'),
      value: String(stats.discussions),
      helper: t('blackboard.metrics.openThreads', {
        count: stats.openPosts,
        defaultValue: '{{count}} open',
      }),
      icon: MessageSquareText,
    },
    {
      key: 'agents',
      label: t('blackboard.metrics.agents', 'Agents'),
      value: String(stats.activeAgents),
      helper: t('blackboard.metrics.activeAgents', 'active now'),
      icon: Bot,
    },
    {
      key: 'humans',
      label: t('blackboard.metrics.humans', 'Human seats'),
      value: String(stats.humanSeats),
      helper: t('blackboard.metrics.coordinationSeats', 'coordination seats'),
      icon: Users,
    },
    {
      key: 'blocked',
      label: t('blackboard.metrics.blocked', 'Blocked'),
      value: String(stats.blockedTasks),
      helper: t('blackboard.metrics.needsAttention', 'needs attention'),
      icon: AlertTriangle,
    },
  ];

  const boardPalette = getNodePalette('blackboard');
  const boardPolygon = toPolygonPoints(0, 0, BOARD_NODE_SIZE);

  return (
    <CanvasErrorBoundary>
    <div className="relative min-h-[520px] overflow-hidden rounded-3xl border border-border-light bg-surface-light shadow-lg dark:border-border-dark dark:bg-background-dark sm:min-h-[620px]">
      <div className="pointer-events-none absolute inset-x-0 top-0 z-20 flex flex-col gap-3 p-4 sm:p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="pointer-events-auto max-w-3xl rounded-3xl border border-border-light bg-surface-light/96 px-5 py-4 shadow-md dark:border-border-dark dark:bg-surface-dark-alt/92">
            <div className="text-[11px] uppercase tracking-[0.32em] text-primary/75 dark:text-primary/80">
              {t('blackboard.commandCenter', 'Workspace command center')}
            </div>
            <h2 className="mt-2 break-words text-2xl font-semibold text-text-primary dark:text-text-inverse">
              {workspaceName}
            </h2>
            <p className="mt-2 max-w-xl text-sm leading-6 text-text-secondary dark:text-text-muted">
              {t(
                'blackboard.canvasHint',
                'Use the central blackboard to review execution, align the team, and jump into shared tasks and discussions.'
              )}
            </p>
            <p className="mt-3 text-xs leading-6 text-text-muted dark:text-text-muted">
              {t(
                'blackboard.quickActionsHint',
                'The center tracks completion, discussions, and agent activity. Open it to edit tasks, reply to posts, and inspect topology.'
              )}
            </p>
          </div>

          <button
            type="button"
            onClick={onOpenBlackboard}
            className="pointer-events-auto inline-flex min-h-11 items-center justify-center gap-2 self-start rounded-full border border-primary bg-primary px-4 py-2 text-sm font-medium text-white transition hover:bg-primary-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
          >
            {t('blackboard.openBoard', 'Open central blackboard')}
            <ChevronRight size={16} />
          </button>
        </div>

        <div className="pointer-events-auto flex flex-wrap gap-2">
          {statCards.map((card) => {
            const Icon = card.icon;

            return (
              <div
                key={card.key}
                title={card.helper}
                className="rounded-full border border-border-light bg-surface-light/96 px-3 py-2 shadow-sm dark:border-border-dark dark:bg-surface-dark-alt/90"
              >
                <div className="flex items-center gap-2">
                  <span className="rounded-full border border-border-light bg-surface-muted p-1.5 text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-secondary">
                    <Icon size={14} />
                  </span>
                  <div className="min-w-0">
                    <div className="text-[11px] uppercase tracking-[0.16em] text-text-muted dark:text-text-muted">
                      {card.label}
                    </div>
                    <div className="truncate text-sm font-semibold text-text-primary dark:text-text-inverse">
                      {card.value}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <svg
        className="hidden h-full w-full sm:block"
        aria-labelledby="central-blackboard-canvas-title central-blackboard-canvas-description"
        viewBox={viewBox}
      >
        <title id="central-blackboard-canvas-title">{t('blackboard.title', 'Blackboard')}</title>
        <desc id="central-blackboard-canvas-description">
          {t(
            'blackboard.canvasDescription',
            'Overview of the central blackboard with the main board in the center and connected workstations around it.'
          )}
        </desc>

        {/* Mobile fallback: card list on small screens */}
        <div className="block sm:hidden space-y-3 p-4">
          {pixelActors.map((actor) => {
            const palette = getNodePalette(actor.kind);
            return (
              <div
                key={actor.key}
                className="flex items-center gap-3 rounded-2xl border border-border-light bg-surface-muted px-4 py-3 dark:border-border-dark dark:bg-surface-dark-alt"
              >
                <span
                  className="h-3 w-3 rounded-full"
                  style={{ backgroundColor: palette.stroke }}
                />
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-text-primary dark:text-text-inverse">
                    {truncateLabel(actor.title, 20)}
                  </div>
                  <div className="text-xs text-text-muted">
                    {actor.statusLabel}
                  </div>
                </div>
              </div>
            );
          })}
          {pixelActors.length === 0 && (
            <div className="rounded-2xl border border-dashed border-border-separator bg-surface-light p-4 text-center text-sm text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
              {t('blackboard.noAgents', 'No agents connected yet.')}
            </div>
          )}
        </div>

        {/* SVG canvas on sm+ screens */}
        <defs>
          <filter id="board-node-glow" x="-200%" y="-200%" width="400%" height="400%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="10" result="blurred" />
            <feMerge>
              <feMergeNode in="blurred" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <rect x="-2000" y="-2000" width="4000" height="4000" fill="var(--color-background-dark)" />

        {pixelGrid.map((cell) => (
          <polygon
            key={`grid-${String(cell.q)}-${String(cell.r)}`}
            points={toPolygonPoints(cell.x, cell.y, GRID_HEX_SIZE)}
            fill="transparent"
            stroke="var(--color-border-dark)"
            strokeOpacity={0.55}
            strokeWidth={1.4}
          />
        ))}

        {pixelActors.map((actor) => (
          <line
            key={`central-link-${actor.key}`}
            x1={0}
            y1={0}
            x2={actor.x}
            y2={actor.y}
            stroke="var(--color-primary-light)"
            strokeOpacity={0.22}
            strokeWidth={6}
            strokeLinecap="round"
          />
        ))}

        {pixelLinks.map((link) => (
          <line
            key={link.id}
            x1={link.fromPixel.x}
            y1={link.fromPixel.y}
            x2={link.toPixel.x}
            y2={link.toPixel.y}
            stroke="var(--color-border-separator-dark)"
            strokeOpacity={0.62}
            strokeWidth={4}
            strokeLinecap="round"
          />
        ))}

        <g
          role="button"
          tabIndex={0}
          aria-label={t('blackboard.openBoard', 'Open central blackboard')}
          onClick={onOpenBlackboard}
          onKeyDown={(event: React.KeyboardEvent<SVGGElement>) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              onOpenBlackboard();
            }
          }}
          style={{ cursor: 'pointer' }}
        >
          <polygon
            points={boardPolygon}
            fill={boardPalette.glow}
            fillOpacity={0.09}
            filter="url(#board-node-glow)"
          />
          <polygon
            points={boardPolygon}
            fill={boardPalette.fill}
            stroke={boardPalette.stroke}
            strokeWidth={7}
          />
          <polygon
            points={toPolygonPoints(0, 0, BOARD_NODE_SIZE - 10)}
            fill="transparent"
            stroke="var(--color-primary-light)"
            strokeWidth={2}
            strokeOpacity={0.82}
          />

          <text
            x={0}
            y={-18}
            textAnchor="middle"
            fontSize={32}
            fontWeight={600}
            fill={boardPalette.text}
          >
            {t('blackboard.title', 'Blackboard')}
          </text>
          <text
            x={0}
            y={28}
            textAnchor="middle"
            fontSize={22}
            fontWeight={500}
            fill={boardPalette.muted}
          >
            {t('blackboard.completionSummary', {
              done: stats.completedTasks,
              total: stats.totalTasks,
              defaultValue: '{{done}} / {{total}} tasks complete',
            })}
          </text>
          <text x={0} y={66} textAnchor="middle" fontSize={18} fill="var(--color-primary-200)">
            {t('blackboard.boardSummaryLine', {
              posts: stats.discussions,
              pinned: stats.pinnedPosts,
              defaultValue: '{{posts}} discussions · {{pinned}} pinned',
            })}
          </text>
        </g>

        {pixelActors.map((actor) => {
          const palette = getNodePalette(actor.kind);
          const polygon = toPolygonPoints(actor.x, actor.y, OUTER_NODE_SIZE);
          const topTextX = actor.x - OUTER_NODE_SIZE * 0.42;
          const topTextY = actor.y - OUTER_NODE_SIZE * 0.52;

          return (
            <g
              key={actor.key}
              role="img"
              aria-label={`${actor.kind === 'agent' ? t('blackboard.agent', 'Agent') : t('blackboard.human', 'Human')}: ${actor.title} (${actor.statusLabel})`}
            >
              <polygon
                points={polygon}
                fill={palette.glow}
                fillOpacity={0.05}
                filter="url(#board-node-glow)"
              />
              <polygon
                points={polygon}
                fill={palette.fill}
                stroke={palette.stroke}
                strokeWidth={6}
              />
              <polygon
                points={toPolygonPoints(actor.x, actor.y, OUTER_NODE_SIZE - 8)}
                fill="transparent"
                stroke={palette.stroke}
                strokeOpacity={0.86}
                strokeWidth={1.8}
              />

              <text
                x={topTextX}
                y={topTextY}
                transform={`rotate(-26 ${String(topTextX)} ${String(topTextY)})`}
                textAnchor="start"
                fontSize={16}
                fontWeight={500}
                fill={palette.muted}
              >
                {actor.statusLabel}
              </text>

              <text
                x={actor.x}
                y={actor.y + 8}
                textAnchor="middle"
                fontSize={28}
                fontWeight={500}
                fill={palette.text}
              >
                {truncateLabel(actor.title, 10)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
    </CanvasErrorBoundary>
  );
}
