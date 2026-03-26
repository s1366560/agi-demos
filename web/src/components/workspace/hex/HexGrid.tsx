import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import type { FC, MouseEvent as ReactMouseEvent } from 'react';

import { useHexDragDrop } from '@/hooks/useHexDragDrop';
import { useHexSelection } from '@/hooks/useHexSelection';

import { HexAgent } from './HexAgent';
import { HexCell } from './HexCell';
import { HexCorridor } from './HexCorridor';
import { HexFlowAnimation } from './HexFlowAnimation';
import { HexHumanSeat } from './HexHumanSeat';
import { HexMiniMap } from './HexMiniMap';
import { HexObjective } from './HexObjective';
import { HexTooltip } from './HexTooltip';
import { useHexLayout } from './useHexLayout';

import type { WorkspaceAgent, TopologyNode, TopologyEdge, CyberObjective } from '@/types/workspace';



import type { MiniMapCell } from './HexMiniMap';

export interface HexGridProps {
  agents: WorkspaceAgent[];
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  objectives?: CyberObjective[] | undefined;
  onSelectHex?: ((q: number, r: number) => void) | undefined;
  onMoveAgent?: ((agentId: string, q: number, r: number) => void) | undefined;
  onContextMenu?: ((q: number, r: number, e: ReactMouseEvent) => void) | undefined;
  gridRadius?: number | undefined;
  hexSize?: number | undefined;
}

export const HexGrid: FC<HexGridProps> = ({
  agents,
  nodes,
  edges,
  objectives = [],
  onSelectHex,
  onMoveAgent,
  onContextMenu,
  gridRadius = 5,
  hexSize = 40.0,
}) => {
  const { gridCells, hexToPixel, pixelToHex, getHexCorners } = useHexLayout({ size: hexSize, gridRadius });
  const svgRef = useRef<SVGSVGElement>(null);

  const [zoom, setZoom] = useState<number>(1);
  const [pan, setPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState<boolean>(false);
  const [dragStart, setDragStart] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

  const [containerSize, setContainerSize] = useState({ width: 800, height: 600 });

  const { isSelected, toggleSelect, selectSingle, clearSelection, selectAll } = useHexSelection();
  const { isDragging: isAgentDragging, draggedAgentId, dragTarget, startDrag, updateDragTarget, endDrag, cancelDrag } = useHexDragDrop();

  const [hoverInfo, setHoverInfo] = useState<{
    visible: boolean;
    x: number;
    y: number;
    title: string;
    details?: Record<string, string> | undefined;
  } | null>(null);

  const occupantMap = useMemo(() => {
    const map = new Map<
      string,
      { type: 'agent' | 'human_seat' | 'corridor' | 'objective'; data: WorkspaceAgent | TopologyNode | CyberObjective }
    >();
    agents.forEach((a) => {
      if (a.hex_q !== undefined && a.hex_r !== undefined) {
        map.set(`${a.hex_q},${a.hex_r}`, { type: 'agent', data: a });
      }
    });
    nodes.forEach((n) => {
      if (n.node_type === 'objective') {
        const obj = (objectives || []).find((o) => o.id === n.ref_id);
        if (obj && n.hex_q !== undefined && n.hex_r !== undefined) {
          map.set(`${n.hex_q},${n.hex_r}`, { type: 'objective', data: obj });
        }
      } else if (n.hex_q !== undefined && n.hex_r !== undefined) {
        map.set(`${n.hex_q},${n.hex_r}`, {
          type: n.node_type === 'human_seat' ? 'human_seat' : 'corridor',
          data: n,
        });
      }
    });
    return map;
  }, [agents, nodes, objectives]);

  const handleWheel = useCallback((e: WheelEvent) => {
    e.preventDefault();
    setZoom((prev) => {
      const newZoom = prev - e.deltaY * 0.001;
      return Math.min(Math.max(newZoom, 0.3), 3.0);
    });
  }, []);

  useEffect(() => {
    const svgElement = svgRef.current;
    if (!svgElement) return;
    
    svgElement.addEventListener('wheel', handleWheel, { passive: false });
    return () => { svgElement.removeEventListener('wheel', handleWheel); };
  }, [handleWheel]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        clearSelection();
        cancelDrag();
      }
      if ((e.ctrlKey || e.metaKey) && e.key === 'a') {
        const keys = Array.from(occupantMap.keys());
        if (keys.length > 0) {
          e.preventDefault();
          selectAll(keys);
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => { window.removeEventListener('keydown', handleKeyDown); };
  }, [clearSelection, cancelDrag, selectAll, occupantMap]);

  useEffect(() => {
    const svgElement = svgRef.current;
    if (!svgElement) return;
    
    const observer = new ResizeObserver((entries) => {
      if (entries[0]) {
        setContainerSize({
          width: entries[0].contentRect.width,
          height: entries[0].contentRect.height
        });
      }
    });
    observer.observe(svgElement);
    return () => { observer.disconnect(); };
  }, []);

  const handleMouseDown = (e: ReactMouseEvent<SVGSVGElement>) => {
    if (e.button !== 0) return;
    setIsPanning(true);
    setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
  };

  const handleMouseMove = (e: ReactMouseEvent<SVGSVGElement>) => {
    if (isPanning) {
      setPan({ x: e.clientX - dragStart.x, y: e.clientY - dragStart.y });
    } else if (isAgentDragging && svgRef.current) {
      const rect = svgRef.current.getBoundingClientRect();
      const localX = (e.clientX - rect.left - pan.x) / zoom;
      const localY = (e.clientY - rect.top - pan.y) / zoom;
      const { q, r } = pixelToHex(localX, localY);
      updateDragTarget(q, r);
    }
  };

  const handleMouseUp = () => {
    if (isPanning) {
      setIsPanning(false);
    }
    if (isAgentDragging) {
      endDrag(onMoveAgent);
    }
  };

  const handleMouseLeave = () => {
    if (isPanning) setIsPanning(false);
    if (isAgentDragging) cancelDrag();
  };

  const handleHexClick = (e: ReactMouseEvent, q: number, r: number) => {
    if (e.shiftKey) {
      toggleSelect(q, r);
    } else {
      selectSingle(q, r);
      if (onSelectHex) onSelectHex(q, r);
    }
  };

  const handleContextMenu = (q: number, r: number, e: ReactMouseEvent<SVGGElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (onContextMenu) onContextMenu(q, r, e);
  };

  const handleAgentMouseDown = (e: ReactMouseEvent, occupant: { type: "agent" | "human_seat" | "corridor" | "objective"; data: WorkspaceAgent | TopologyNode | CyberObjective }, q: number, r: number) => {
    if (e.button !== 0) return;
    if (occupant.type === 'agent') {
      e.stopPropagation();
      startDrag((occupant.data as WorkspaceAgent).agent_id, q, r);
    }
  };

  const miniMapCells: MiniMapCell[] = useMemo(() => {
    return gridCells.map(cell => {
      const occupant = occupantMap.get(`${cell.q},${cell.r}`);
      return {
        q: cell.q,
        r: cell.r,
        type: occupant?.type ?? 'empty'
      };
    });
  }, [gridCells, occupantMap]);

  const handleMiniMapNavigate = useCallback((x: number, y: number) => {
    if (svgRef.current) {
      const rect = svgRef.current.getBoundingClientRect();
      setPan({
        x: -x * zoom + rect.width / 2,
        y: -y * zoom + rect.height / 2,
      });
    }
  }, [zoom]);

  const draggedAgent = useMemo(() => agents.find(a => a.agent_id === draggedAgentId), [agents, draggedAgentId]);

  return (
    <div className="relative w-full h-full bg-[#f8f9fb] overflow-hidden">
      <svg
        ref={svgRef}
        className="w-full h-full"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
      >
        <defs>
          <style>
            {`
              @keyframes hexFlowDash {
                to { stroke-dashoffset: -20; }
              }
              .hex-flow-path {
                animation: hexFlowDash 1s linear infinite;
              }
            `}
          </style>
        </defs>
        <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
          {gridCells.map(({ q, r }) => {
            const { x, y } = hexToPixel(q, r);
            const occupant = occupantMap.get(`${q},${r}`);
            const selected = isSelected(q, r);
            const isDragTarget = isAgentDragging && dragTarget?.q === q && dragTarget?.r === r;
            const corners = getHexCorners(x, y).map(p => `${p.x},${p.y}`).join(' ');

            return (
              <g 
                key={`cell-wrap-${q}-${r}`}
                onClickCapture={(e) => { handleHexClick(e, q, r); }}
              >
                <HexCell
                  q={q}
                  r={r}
                  cx={x}
                  cy={y}
                  size={hexSize}
                  selected={selected}
                  occupied={!!occupant}
                  cellType={occupant?.type ?? 'empty'}
                  onClick={() => {}}
                  onContextMenu={(e) => { handleContextMenu(q, r, e); }}
                />
                {selected && (
                  <polygon
                    points={corners}
                    fill="none"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    style={{ pointerEvents: 'none' }}
                  />
                )}
                {isDragTarget && (
                  <polygon
                    points={corners}
                    fill="none"
                    stroke="#f59e0b"
                    strokeWidth={2}
                    strokeDasharray="4 4"
                    style={{ pointerEvents: 'none' }}
                  />
                )}
              </g>
            );
          })}

          {edges.map((edge) => {
            if (
              edge.source_hex_q === undefined ||
              edge.source_hex_r === undefined ||
              edge.target_hex_q === undefined ||
              edge.target_hex_r === undefined
            ) {
              return null;
            }
            const from = hexToPixel(edge.source_hex_q, edge.source_hex_r);
            const to = hexToPixel(edge.target_hex_q, edge.target_hex_r);
            return (
              <HexFlowAnimation
                key={`edge-${edge.id}`}
                fromX={from.x}
                fromY={from.y}
                toX={to.x}
                toY={to.y}
                direction={edge.direction ?? 'forward'}
                animated={true}
              />
            );
          })}

          {gridCells.map(({ q, r }) => {
            const { x, y } = hexToPixel(q, r);
            const occupant = occupantMap.get(`${q},${r}`);
            if (!occupant) return null;

            return (
              <g
                key={`occupant-${q}-${r}`}
                onMouseEnter={(e) => {
                  const rect = e.currentTarget.getBoundingClientRect();
                  const details: Record<string, string> = {};
                  let title = '';

                  if (occupant.type === 'agent') {
                    const agent = occupant.data as WorkspaceAgent;
                    title = agent.display_name || agent.agent_id;
                    details['Status'] = agent.status || 'unknown';
                    details['ID'] = agent.agent_id;
                  } else if (occupant.type === 'objective') {
                    const obj = occupant.data as CyberObjective;
                    title = obj.title || 'Objective';
                    details['Type'] = obj.obj_type;
                    details['Progress'] = `${obj.progress || 0}%`;
                  } else {
                    const node = occupant.data as TopologyNode;
                    title = node.title || node.node_type;
                    details['Type'] = node.node_type;
                    if (node.status) details['Status'] = node.status;
                  }

                  setHoverInfo({
                    visible: true,
                    x: rect.left + rect.width / 2,
                    y: rect.top,
                    title,
                    details,
                  });
                }}
                onMouseLeave={() => { setHoverInfo(null); }}
                onMouseDown={(e) => { handleAgentMouseDown(e, occupant, q, r); }}
                style={{ 
                  pointerEvents: 'all', 
                  cursor: occupant.type === 'agent' ? 'grab' : 'default',
                  opacity: isAgentDragging && draggedAgentId === (occupant.data as WorkspaceAgent).agent_id ? 0.3 : 1
                }}
              >
                {occupant.type === 'agent' && (
                  <HexAgent agent={occupant.data as WorkspaceAgent} cx={x} cy={y} size={hexSize} />
                )}
                {occupant.type === 'corridor' && (
                  <HexCorridor cx={x} cy={y} size={hexSize} node={occupant.data as TopologyNode} />
                )}
                {occupant.type === 'human_seat' && (
                  <HexHumanSeat
                    cx={x}
                    cy={y}
                    size={hexSize}
                    node={occupant.data as TopologyNode}
                    userName={(occupant.data as TopologyNode).title}
                  />
                )}
                {occupant.type === 'objective' && (
                  <HexObjective
                    cx={x}
                    cy={y}
                    size={hexSize}
                    objective={occupant.data as CyberObjective}
                  />
                )}
              </g>
            );
          })}
          
          {isAgentDragging && draggedAgent && dragTarget && (
            <g style={{ opacity: 0.5, pointerEvents: 'none' }}>
              <HexAgent 
                agent={draggedAgent} 
                cx={hexToPixel(dragTarget.q, dragTarget.r).x} 
                cy={hexToPixel(dragTarget.q, dragTarget.r).y} 
                size={hexSize} 
              />
            </g>
          )}
        </g>
      </svg>

      <HexMiniMap
        cells={miniMapCells}
        viewBox={{
          x: -pan.x / zoom,
          y: -pan.y / zoom,
          width: containerSize.width / zoom,
          height: containerSize.height / zoom,
        }}
        containerSize={containerSize}
        onNavigate={handleMiniMapNavigate}
      />

      {hoverInfo && hoverInfo.visible && (
        <HexTooltip
          x={hoverInfo.x}
          y={hoverInfo.y}
          visible={hoverInfo.visible}
          title={hoverInfo.title}
          {...(hoverInfo.details ? { details: hoverInfo.details } : {})}
          onClose={() => { setHoverInfo(null); }}
        />
      )}
    </div>
  );
};
