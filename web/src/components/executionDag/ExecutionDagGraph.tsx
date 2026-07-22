import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, KeyboardEvent, PointerEvent, WheelEvent } from 'react';

import { useTranslation } from 'react-i18next';

import {
  Activity,
  CheckCircle2,
  CircleDashed,
  Crosshair,
  Download,
  GitBranch,
  Hand,
  LocateFixed,
  MapIcon,
  Maximize2,
  Minus,
  MousePointer2,
  PackageCheck,
  Plus,
  RotateCcw,
  ShieldCheck,
  UserCircle,
  XCircle,
} from 'lucide-react';

import {
  NODE_HEIGHT,
  NODE_WIDTH,
  buildLayout,
  centerScrollOffsetScaled,
  edgeKey,
  edgePath,
} from './ExecutionDagGraphLayout';
import { GraphMinimap, GraphToolButton } from './ExecutionDagGraphTools';

import type { GraphLayout, GraphViewport } from './ExecutionDagGraphLayout';
import type { ExecutionDagModel } from './types';

const MIN_ZOOM = 0.45;
const MAX_ZOOM = 2.25;
const ZOOM_FACTOR = 1.18;

const STATUS_TONE: Record<string, string> = {
  done: 'border-success-border bg-success-bg text-status-text-success dark:border-success-border-dark dark:bg-success-bg-dark dark:text-status-text-success-dark',
  completed:
    'border-success-border bg-success-bg text-status-text-success dark:border-success-border-dark dark:bg-success-bg-dark dark:text-status-text-success-dark',
  in_progress:
    'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark',
  running:
    'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark',
  dispatched:
    'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark',
  verifying:
    'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark',
  reported:
    'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark',
  blocked:
    'border-error-border bg-error-bg text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark',
  failed:
    'border-error-border bg-error-bg text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark',
  skipped:
    'border-warning-border bg-warning-bg text-status-text-warning dark:border-warning-border-dark dark:bg-warning-bg-dark dark:text-status-text-warning-dark',
  cancelled:
    'border-border-light bg-surface-muted text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted',
  todo: 'border-border-light bg-surface-muted text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted',
  pending:
    'border-border-light bg-surface-muted text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted',
};

export interface ExecutionDagGraphProps {
  model: ExecutionDagModel | null;
  selectedNodeId?: string | null | undefined;
  highlightedNodeId?: string | null | undefined;
  dimmedNodeIds?: ReadonlySet<string> | undefined;
  onNodeSelect?: ((nodeId: string) => void) | undefined;
  className?: string | undefined;
  minHeight?: number | undefined;
  fitToWidth?: boolean | undefined;
}

type GraphViewMode = 'fit' | 'manual';

interface PanState {
  pointerId: number;
  startX: number;
  startY: number;
  scrollLeft: number;
  scrollTop: number;
}

function statusTone(status: string): string {
  return (
    STATUS_TONE[status] ??
    'border-border-light bg-surface-muted text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted'
  );
}

function statusIcon(status: string, execution: string | undefined) {
  if (status === 'done' || status === 'completed') {
    return <CheckCircle2 className="h-4 w-4 text-status-text-success" aria-hidden />;
  }
  if (status === 'blocked' || status === 'failed') {
    return <XCircle className="h-4 w-4 text-status-text-error" aria-hidden />;
  }
  if (execution === 'verifying' || execution === 'reported') {
    return <ShieldCheck className="h-4 w-4 text-status-text-info" aria-hidden />;
  }
  if (status === 'in_progress' || status === 'running' || execution === 'running') {
    return <Activity className="h-4 w-4 text-status-text-info" aria-hidden />;
  }
  return <CircleDashed className="h-4 w-4 text-text-muted" aria-hidden />;
}

function clampZoom(value: number): number {
  return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, value));
}

function formatZoom(value: number): string {
  return `${String(Math.round(value * 100))}%`;
}

function renderedScale(
  container: HTMLDivElement | null,
  layout: GraphLayout | null,
  viewMode: GraphViewMode,
  manualZoom: number
): number {
  if (!container || !layout || viewMode === 'manual') {
    return manualZoom;
  }

  if (container.clientWidth <= 0 || layout.width <= 0) {
    return 1;
  }

  return Math.max(0.05, container.clientWidth / layout.width);
}

export const ExecutionDagGraph = memo<ExecutionDagGraphProps>(
  ({
    model,
    selectedNodeId,
    highlightedNodeId,
    dimmedNodeIds,
    onNodeSelect,
    className = '',
    minHeight = 520,
    fitToWidth = false,
  }) => {
    const { t } = useTranslation();
    const scrollContainerRef = useRef<HTMLDivElement | null>(null);
    const panStateRef = useRef<PanState | null>(null);
    const layout = useMemo(() => (model ? buildLayout(model) : null), [model]);
    const [viewMode, setViewMode] = useState<GraphViewMode>(fitToWidth ? 'fit' : 'manual');
    const [manualZoom, setManualZoom] = useState(1);
    const [isPanMode, setIsPanMode] = useState(false);
    const [showOverview, setShowOverview] = useState(true);
    const [viewport, setViewport] = useState<GraphViewport>({
      left: 0,
      top: 0,
      width: 0,
      height: 0,
      scale: 1,
    });
    const currentScale = viewMode === 'fit' ? viewport.scale : manualZoom;
    const zoomDisplay =
      viewMode === 'fit'
        ? t('executionDag.fitZoom', { defaultValue: 'Fit' })
        : formatZoom(currentScale);
    const graphStats = useMemo(() => {
      if (!layout) {
        return { nodes: 0, edges: 0 };
      }
      return {
        nodes: layout.nodes.length,
        edges: layout.edges.length,
      };
    }, [layout]);

    const refreshViewport = useCallback(() => {
      const container = scrollContainerRef.current;
      if (!container || !layout) {
        return;
      }
      const scale = renderedScale(container, layout, viewMode, manualZoom);
      setViewport({
        left: container.scrollLeft / scale,
        top: container.scrollTop / scale,
        width: container.clientWidth / scale,
        height: container.clientHeight / scale,
        scale,
      });
    }, [layout, manualZoom, viewMode]);

    const getScale = useCallback(() => {
      return renderedScale(scrollContainerRef.current, layout, viewMode, manualZoom);
    }, [layout, manualZoom, viewMode]);

    const centerGraphPoint = useCallback(
      (x: number, y: number, behavior?: ScrollBehavior) => {
        const container = scrollContainerRef.current;
        if (!container || !layout) {
          return;
        }
        const scale = getScale();
        container.scrollTo({
          left: Math.max(0, x * scale - container.clientWidth / 2),
          top: Math.max(0, y * scale - container.clientHeight / 2),
          behavior: behavior ?? 'smooth',
        });
      },
      [getScale, layout]
    );

    const centerNode = useCallback(
      (nodeId: string | null | undefined, behavior?: ScrollBehavior) => {
        if (!nodeId || !layout) {
          return;
        }
        const container = scrollContainerRef.current;
        const node = layout.byId.get(nodeId);
        if (!container || !node) {
          return;
        }
        const scale = getScale();
        container.scrollTo({
          left: centerScrollOffsetScaled(node.x, NODE_WIDTH, container.clientWidth, scale),
          top: centerScrollOffsetScaled(node.y, NODE_HEIGHT, container.clientHeight, scale),
          behavior: behavior ?? 'smooth',
        });
      },
      [getScale, layout]
    );

    const setManualZoomFrom = useCallback((nextZoom: number) => {
      setViewMode('manual');
      setManualZoom(clampZoom(nextZoom));
    }, []);

    const getZoomBase = useCallback(() => {
      return viewMode === 'fit' ? getScale() : manualZoom;
    }, [getScale, manualZoom, viewMode]);

    const zoomIn = useCallback(() => {
      setManualZoomFrom(getZoomBase() * ZOOM_FACTOR);
    }, [getZoomBase, setManualZoomFrom]);

    const zoomOut = useCallback(() => {
      setManualZoomFrom(getZoomBase() / ZOOM_FACTOR);
    }, [getZoomBase, setManualZoomFrom]);

    const resetView = useCallback(() => {
      setManualZoom(1);
      setViewMode(fitToWidth ? 'fit' : 'manual');
      const container = scrollContainerRef.current;
      if (container) {
        container.scrollTo({ left: 0, top: 0, behavior: 'smooth' });
      }
    }, [fitToWidth]);

    const exportSvg = useCallback(() => {
      const svg = scrollContainerRef.current?.querySelector('svg');
      if (!svg) {
        return;
      }
      const clone = svg.cloneNode(true) as SVGSVGElement;
      clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
      clone.setAttribute('width', String(layout?.width ?? 0));
      clone.setAttribute('height', String(layout?.height ?? 0));
      const blob = new Blob([new XMLSerializer().serializeToString(clone)], {
        type: 'image/svg+xml;charset=utf-8',
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'execution-dag.svg';
      link.click();
      URL.revokeObjectURL(url);
    }, [layout]);

    const handlePointerDown = useCallback(
      (event: PointerEvent<HTMLDivElement>) => {
        if (!isPanMode || event.button !== 0) {
          return;
        }
        const target = event.target as HTMLElement;
        if (target.closest('button, input, a, select, textarea')) {
          return;
        }
        const container = scrollContainerRef.current;
        if (!container) {
          return;
        }
        panStateRef.current = {
          pointerId: event.pointerId,
          startX: event.clientX,
          startY: event.clientY,
          scrollLeft: container.scrollLeft,
          scrollTop: container.scrollTop,
        };
        event.currentTarget.setPointerCapture(event.pointerId);
      },
      [isPanMode]
    );

    const handlePointerMove = useCallback(
      (event: PointerEvent<HTMLDivElement>) => {
        const panState = panStateRef.current;
        const container = scrollContainerRef.current;
        if (!panState || !container || panState.pointerId !== event.pointerId) {
          return;
        }
        container.scrollLeft = panState.scrollLeft - (event.clientX - panState.startX);
        container.scrollTop = panState.scrollTop - (event.clientY - panState.startY);
        refreshViewport();
      },
      [refreshViewport]
    );

    const handlePointerUp = useCallback((event: PointerEvent<HTMLDivElement>) => {
      if (panStateRef.current?.pointerId === event.pointerId) {
        panStateRef.current = null;
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
    }, []);

    const handleWheel = useCallback(
      (event: WheelEvent<HTMLDivElement>) => {
        if (!event.ctrlKey && !event.metaKey) {
          return;
        }
        event.preventDefault();
        if (event.deltaY < 0) {
          zoomIn();
        } else {
          zoomOut();
        }
      },
      [zoomIn, zoomOut]
    );

    const handleKeyboard = useCallback(
      (event: KeyboardEvent<HTMLDivElement>) => {
        const target = event.target as HTMLElement;
        if (target.closest('button, input, a, select, textarea')) {
          return;
        }
        if (event.key === '+' || event.key === '=') {
          event.preventDefault();
          zoomIn();
        } else if (event.key === '-') {
          event.preventDefault();
          zoomOut();
        } else if (event.key === '0') {
          event.preventDefault();
          resetView();
        } else if (event.key.toLowerCase() === 'f') {
          event.preventDefault();
          setViewMode('fit');
        } else if (event.key.toLowerCase() === 'p') {
          event.preventDefault();
          setIsPanMode((value) => !value);
        }
      },
      [resetView, zoomIn, zoomOut]
    );

    useEffect(() => {
      if (!layout || !highlightedNodeId) {
        return;
      }

      centerNode(highlightedNodeId, 'auto');
    }, [centerNode, highlightedNodeId, layout]);

    useEffect(() => {
      const container = scrollContainerRef.current;
      if (!container) {
        return;
      }
      refreshViewport();
      container.addEventListener('scroll', refreshViewport, { passive: true });
      window.addEventListener('resize', refreshViewport);
      return () => {
        container.removeEventListener('scroll', refreshViewport);
        window.removeEventListener('resize', refreshViewport);
      };
    }, [refreshViewport]);

    if (!model || model.nodes.length === 0 || !layout) {
      return (
        <div
          className={`flex min-h-[320px] items-center justify-center rounded-md border border-border-light bg-surface-light text-sm text-text-muted dark:border-border-dark dark:bg-surface-dark ${className}`}
          data-testid="execution-dag-empty"
        >
          <div className="text-center">
            <GitBranch className="mx-auto h-8 w-8 text-text-muted" aria-hidden />
            <p className="mt-2">
              {t('executionDag.empty', {
                defaultValue: 'No execution graph is available.',
              })}
            </p>
          </div>
        </div>
      );
    }

    const svgStyle: CSSProperties =
      viewMode === 'fit'
        ? { width: '100%', height: 'auto' }
        : {
            width: `${String(Math.round(layout.width * manualZoom))}px`,
            height: `${String(Math.round(layout.height * manualZoom))}px`,
          };
    const canvasMinHeight = Math.max(260, minHeight - 48);

    return (
      <div
        className={`relative flex min-h-0 flex-col overflow-hidden rounded-md border border-border-light bg-surface-light dark:border-border-dark dark:bg-surface-dark ${className}`}
        style={{ minHeight }}
        data-fit-to-width={viewMode === 'fit' ? 'true' : undefined}
        data-testid="execution-dag-graph"
        role="group"
        aria-label={t('executionDag.ariaLabel', { defaultValue: 'Execution graph' })}
        tabIndex={0}
        onKeyDown={handleKeyboard}
      >
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 border-b border-border-separator bg-surface-muted px-2 py-2 dark:border-border-dark dark:bg-surface-dark-alt">
          <div className="flex min-w-0 items-center gap-2">
            <span className="inline-flex h-7 items-center rounded border border-border-light bg-surface-light px-2 font-mono text-[11px] text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
              {t('executionDag.graphStats', {
                defaultValue: '{{nodes}} nodes · {{edges}} edges',
                nodes: graphStats.nodes,
                edges: graphStats.edges,
              })}
            </span>
            <span className="inline-flex h-7 items-center rounded border border-border-light bg-surface-light px-2 font-mono text-[11px] text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
              {zoomDisplay}
            </span>
          </div>
          <div
            role="toolbar"
            className="flex min-w-0 flex-wrap items-center gap-1.5"
            aria-label={t('executionDag.tools', { defaultValue: 'Graph tools' })}
          >
            <GraphToolButton
              label={t('executionDag.zoomOut', { defaultValue: 'Zoom out' })}
              onClick={zoomOut}
            >
              <Minus className="h-3.5 w-3.5" aria-hidden />
            </GraphToolButton>
            <label className="flex h-8 w-28 items-center rounded border border-border-light bg-surface-light px-2 dark:border-border-dark dark:bg-surface-dark">
              <span className="sr-only">
                {t('executionDag.zoomSlider', { defaultValue: 'Zoom level' })}
              </span>
              <input
                type="range"
                min={Math.round(MIN_ZOOM * 100)}
                max={Math.round(MAX_ZOOM * 100)}
                step="5"
                value={Math.round(clampZoom(currentScale) * 100)}
                onChange={(event) => {
                  setManualZoomFrom(Number(event.target.value) / 100);
                }}
                className="h-1.5 w-full accent-primary"
              />
            </label>
            <GraphToolButton
              label={t('executionDag.zoomIn', { defaultValue: 'Zoom in' })}
              onClick={zoomIn}
            >
              <Plus className="h-3.5 w-3.5" aria-hidden />
            </GraphToolButton>
            <GraphToolButton
              active={viewMode === 'fit'}
              label={t('executionDag.fitView', { defaultValue: 'Fit width' })}
              onClick={() => {
                setViewMode('fit');
              }}
            >
              <Maximize2 className="h-3.5 w-3.5" aria-hidden />
            </GraphToolButton>
            <GraphToolButton
              active={viewMode === 'manual' && Math.abs(manualZoom - 1) < 0.01}
              label={t('executionDag.actualSize', { defaultValue: 'Actual size' })}
              onClick={() => {
                setManualZoomFrom(1);
              }}
            >
              <MousePointer2 className="h-3.5 w-3.5" aria-hidden />
            </GraphToolButton>
            <GraphToolButton
              label={t('executionDag.resetView', { defaultValue: 'Reset view' })}
              onClick={resetView}
            >
              <RotateCcw className="h-3.5 w-3.5" aria-hidden />
            </GraphToolButton>
            <GraphToolButton
              active={isPanMode}
              label={t('executionDag.panMode', { defaultValue: 'Drag to pan' })}
              onClick={() => {
                setIsPanMode((value) => !value);
              }}
            >
              <Hand className="h-3.5 w-3.5" aria-hidden />
            </GraphToolButton>
            <GraphToolButton
              disabled={!selectedNodeId}
              label={t('executionDag.centerSelected', { defaultValue: 'Center selected node' })}
              onClick={() => {
                centerNode(selectedNodeId);
              }}
            >
              <LocateFixed className="h-3.5 w-3.5" aria-hidden />
            </GraphToolButton>
            <GraphToolButton
              label={t('executionDag.centerCurrent', {
                defaultValue: 'Center current or root node',
              })}
              onClick={() => {
                centerNode(highlightedNodeId ?? model.rootId);
              }}
            >
              <Crosshair className="h-3.5 w-3.5" aria-hidden />
            </GraphToolButton>
            <GraphToolButton
              active={showOverview}
              label={t('executionDag.toggleOverview', { defaultValue: 'Toggle overview map' })}
              onClick={() => {
                setShowOverview((value) => !value);
              }}
            >
              <MapIcon className="h-3.5 w-3.5" aria-hidden />
            </GraphToolButton>
            <GraphToolButton
              label={t('executionDag.downloadSvg', { defaultValue: 'Download SVG' })}
              onClick={exportSvg}
            >
              <Download className="h-3.5 w-3.5" aria-hidden />
            </GraphToolButton>
          </div>
        </div>
        <div
          ref={scrollContainerRef}
          className={`relative min-h-0 flex-1 overflow-auto bg-surface-light dark:bg-surface-dark ${
            isPanMode ? 'cursor-grab active:cursor-grabbing' : ''
          }`}
          style={{ minHeight: canvasMinHeight }}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
          onWheel={handleWheel}
          onScroll={refreshViewport}
          data-testid="execution-dag-canvas"
        >
          <svg
            width={layout.width}
            height={layout.height}
            viewBox={`0 0 ${String(layout.width)} ${String(layout.height)}`}
            style={svgStyle}
            className={viewMode === 'fit' ? 'h-auto w-full' : 'mx-auto max-w-none'}
            role="img"
            aria-label={t('executionDag.ariaLabel', {
              defaultValue: 'Execution DAG',
            })}
            data-testid="execution-dag-svg"
          >
            <title>{t('executionDag.ariaLabel', { defaultValue: 'Execution DAG' })}</title>
            <defs>
              <marker
                id="execution-dag-arrow-dependency"
                viewBox="0 0 10 10"
                refX="8"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" className="fill-text-muted" />
              </marker>
              <marker
                id="execution-dag-arrow-handoff"
                viewBox="0 0 10 10"
                refX="8"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" className="fill-status-text-info" />
              </marker>
            </defs>

            {layout.edges.map((edge) => {
              const source = layout.byId.get(edge.sourceId);
              const target = layout.byId.get(edge.targetId);
              if (!source || !target) {
                return null;
              }
              const muted = edge.kind === 'hierarchy';
              const handoff = edge.kind === 'handoff';
              return (
                <path
                  key={edge.id || edgeKey(edge)}
                  d={edgePath(source, target)}
                  fill="none"
                  strokeWidth={handoff ? 2 : 1.5}
                  strokeDasharray={muted ? '4 5' : handoff ? '6 4' : undefined}
                  markerEnd={
                    handoff
                      ? 'url(#execution-dag-arrow-handoff)'
                      : 'url(#execution-dag-arrow-dependency)'
                  }
                  className={
                    handoff
                      ? 'stroke-status-text-info'
                      : muted
                        ? 'stroke-border-light opacity-70 dark:stroke-border-dark'
                        : 'stroke-text-muted'
                  }
                />
              );
            })}

            {layout.nodes.map((node) => {
              const isSelected = selectedNodeId === node.id;
              const isHighlighted = highlightedNodeId === node.id;
              const isDimmed = dimmedNodeIds?.has(node.id) ?? false;
              const selectable = node.selectable !== false && Boolean(onNodeSelect);
              return (
                <foreignObject
                  key={node.id}
                  x={node.x}
                  y={node.y}
                  width={NODE_WIDTH}
                  height={NODE_HEIGHT}
                  className="overflow-visible"
                >
                  <button
                    type="button"
                    disabled={!selectable}
                    onClick={() => {
                      if (selectable) {
                        onNodeSelect?.(node.id);
                      }
                    }}
                    onKeyDown={(event) => {
                      if (!selectable) {
                        return;
                      }
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        onNodeSelect?.(node.id);
                      }
                    }}
                    className={`relative flex h-full w-full flex-col rounded-md border bg-surface-light p-3 text-left shadow-[0_0_0_1px_rgba(0,0,0,0.02)] transition-[border-color,background-color,box-shadow,opacity] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default dark:bg-surface-dark ${
                      isSelected
                        ? 'border-info-border ring-2 ring-ring dark:border-info-border-dark'
                        : isHighlighted
                          ? 'border-warning-border ring-2 ring-status-text-warning/35 dark:border-warning-border-dark dark:ring-status-text-warning-dark/35'
                          : 'border-border-light hover:border-info-border dark:border-border-dark dark:hover:border-info-border-dark'
                    } ${isDimmed ? 'opacity-35' : 'opacity-100'}`}
                    aria-pressed={isSelected}
                    data-current-session-node={isHighlighted ? 'true' : undefined}
                    data-testid={`execution-dag-node-${node.id}`}
                  >
                    {isHighlighted ? (
                      <span className="absolute right-2 top-2 inline-flex h-5 max-w-[112px] items-center rounded-full border border-warning-border bg-warning-bg px-2 text-[10px] font-semibold uppercase text-status-text-warning dark:border-warning-border-dark dark:bg-warning-bg-dark dark:text-status-text-warning-dark">
                        <span className="truncate">
                          {t('executionDag.currentSession', {
                            defaultValue: 'Current session',
                          })}
                        </span>
                      </span>
                    ) : null}
                    <div
                      className={`flex min-w-0 items-start gap-2 ${isHighlighted ? 'pr-[118px]' : ''}`}
                    >
                      <span className="mt-0.5 shrink-0">
                        {statusIcon(node.status, node.execution)}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold leading-5 text-text-primary dark:text-text-inverse">
                          {node.title}
                        </span>
                        {node.subtitle ? (
                          <span className="mt-0.5 block truncate text-[11px] text-text-muted">
                            {node.subtitle}
                          </span>
                        ) : null}
                      </span>
                    </div>

                    <div className="mt-2 flex min-w-0 flex-wrap gap-1.5">
                      <span
                        className={`inline-flex h-5 items-center rounded-full border px-2 text-[10px] font-semibold uppercase ${statusTone(
                          node.status
                        )}`}
                      >
                        {node.status}
                      </span>
                      {node.execution ? (
                        <span className="inline-flex h-5 items-center rounded-full border border-border-light px-2 text-[10px] font-semibold uppercase text-text-secondary dark:border-border-dark dark:text-text-muted">
                          {node.execution}
                        </span>
                      ) : null}
                    </div>

                    <div className="mt-auto min-w-0 space-y-1.5">
                      {typeof node.progress === 'number' ? (
                        <div className="h-1.5 overflow-hidden rounded-full bg-surface-dark/10 dark:bg-surface-light/10">
                          <div
                            className="h-full rounded-full bg-status-text-info transition-[width] motion-reduce:transition-none"
                            style={{
                              width: `${Math.max(0, Math.min(100, node.progress)).toFixed(0)}%`,
                            }}
                          />
                        </div>
                      ) : null}
                      <div className="flex min-w-0 items-center justify-between gap-2 text-[10px] text-text-muted">
                        <span className="flex min-w-0 items-center gap-1 truncate">
                          <UserCircle className="h-3 w-3 shrink-0" aria-hidden />
                          <span className="truncate">
                            {node.agentLabel ||
                              t('executionDag.unassignedAgent', { defaultValue: 'Unassigned' })}
                          </span>
                        </span>
                        <span className="shrink-0 font-mono">{node.attemptId ?? node.kind}</span>
                      </div>
                      {node.metrics ? (
                        <div className="flex min-w-0 items-center gap-2 text-[10px] text-text-muted">
                          <PackageCheck className="h-3 w-3 shrink-0" aria-hidden />
                          <span className="truncate">
                            {t(
                              'executionDag.metrics',
                              '{{evidence}} refs · {{artifacts}} artifacts',
                              {
                                evidence: node.metrics.evidence ?? 0,
                                artifacts: node.metrics.artifacts ?? 0,
                              }
                            )}
                          </span>
                        </div>
                      ) : null}
                    </div>
                  </button>
                </foreignObject>
              );
            })}
          </svg>
        </div>
        {showOverview ? (
          <div
            className="pointer-events-auto absolute bottom-3 right-3 z-10 rounded-md border border-border-light bg-surface-light/95 p-1 shadow-sm dark:border-border-dark dark:bg-surface-dark/95"
            data-testid="execution-dag-minimap-overlay"
          >
            <GraphMinimap
              layout={layout}
              selectedNodeId={selectedNodeId}
              highlightedNodeId={highlightedNodeId}
              viewport={viewport}
              label={t('executionDag.overviewMap', { defaultValue: 'Graph overview map' })}
              onCenterPoint={(x, y) => {
                centerGraphPoint(x, y);
              }}
            />
          </div>
        ) : null}
      </div>
    );
  }
);

ExecutionDagGraph.displayName = 'ExecutionDagGraph';
