import type { ReactNode } from 'react';

import { NODE_HEIGHT, NODE_WIDTH, edgeKey } from './ExecutionDagGraphLayout';

import type { GraphLayout, GraphViewport } from './ExecutionDagGraphLayout';

const MINIMAP_WIDTH = 168;
const MINIMAP_HEIGHT = 104;
const MINIMAP_PADDING = 8;

export function GraphToolButton({
  active = false,
  disabled = false,
  label,
  onClick,
  children,
}: {
  active?: boolean;
  disabled?: boolean;
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-pressed={active || undefined}
      className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded border text-text-secondary transition-colors hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-40 dark:text-text-muted dark:hover:text-text-inverse ${
        active
          ? 'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark'
          : 'border-border-light bg-surface-light hover:bg-surface-muted dark:border-border-dark dark:bg-surface-dark dark:hover:bg-surface-dark-alt'
      }`}
    >
      {children}
    </button>
  );
}

export function GraphMinimap({
  layout,
  selectedNodeId,
  highlightedNodeId,
  viewport,
  label,
  onCenterPoint,
}: {
  layout: GraphLayout;
  selectedNodeId?: string | null | undefined;
  highlightedNodeId?: string | null | undefined;
  viewport: GraphViewport;
  label: string;
  onCenterPoint: (x: number, y: number) => void;
}) {
  const minimapScale = Math.min(
    (MINIMAP_WIDTH - MINIMAP_PADDING * 2) / layout.width,
    (MINIMAP_HEIGHT - MINIMAP_PADDING * 2) / layout.height
  );
  const graphWidth = layout.width * minimapScale;
  const graphHeight = layout.height * minimapScale;
  const offsetX = (MINIMAP_WIDTH - graphWidth) / 2;
  const offsetY = (MINIMAP_HEIGHT - graphHeight) / 2;
  const viewportX = offsetX + viewport.left * minimapScale;
  const viewportY = offsetY + viewport.top * minimapScale;
  const viewportWidth = Math.max(10, viewport.width * minimapScale);
  const viewportHeight = Math.max(10, viewport.height * minimapScale);

  return (
    <svg
      width={MINIMAP_WIDTH}
      height={MINIMAP_HEIGHT}
      viewBox={`0 0 ${String(MINIMAP_WIDTH)} ${String(MINIMAP_HEIGHT)}`}
      role="img"
      aria-label={label}
      onPointerDown={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        const x = (event.clientX - rect.left - offsetX) / minimapScale;
        const y = (event.clientY - rect.top - offsetY) / minimapScale;
        onCenterPoint(x, y);
      }}
      className="block cursor-crosshair"
      data-testid="execution-dag-minimap"
    >
      <rect
        x="0.5"
        y="0.5"
        width={MINIMAP_WIDTH - 1}
        height={MINIMAP_HEIGHT - 1}
        rx="6"
        className="fill-surface-light stroke-border-light dark:fill-surface-dark dark:stroke-border-dark"
      />
      {layout.edges.map((edge) => {
        const source = layout.byId.get(edge.sourceId);
        const target = layout.byId.get(edge.targetId);
        if (!source || !target) {
          return null;
        }
        return (
          <line
            key={edge.id || edgeKey(edge)}
            x1={offsetX + (source.x + NODE_WIDTH / 2) * minimapScale}
            y1={offsetY + (source.y + NODE_HEIGHT) * minimapScale}
            x2={offsetX + (target.x + NODE_WIDTH / 2) * minimapScale}
            y2={offsetY + target.y * minimapScale}
            className="stroke-text-muted opacity-40"
            strokeWidth="0.75"
          />
        );
      })}
      {layout.nodes.map((node) => {
        const selected = node.id === selectedNodeId;
        const highlighted = node.id === highlightedNodeId;
        return (
          <rect
            key={node.id}
            x={offsetX + node.x * minimapScale}
            y={offsetY + node.y * minimapScale}
            width={Math.max(5, NODE_WIDTH * minimapScale)}
            height={Math.max(4, NODE_HEIGHT * minimapScale)}
            rx="2"
            className={
              selected
                ? 'fill-status-text-info'
                : highlighted
                  ? 'fill-status-text-warning'
                  : 'fill-text-muted opacity-50'
            }
          />
        );
      })}
      <rect
        x={Math.max(offsetX, Math.min(offsetX + graphWidth - viewportWidth, viewportX))}
        y={Math.max(offsetY, Math.min(offsetY + graphHeight - viewportHeight, viewportY))}
        width={Math.min(graphWidth, viewportWidth)}
        height={Math.min(graphHeight, viewportHeight)}
        rx="3"
        className="fill-info-bg/35 stroke-status-text-info dark:fill-info-bg-dark/35"
        strokeWidth="1.5"
      />
    </svg>
  );
}
