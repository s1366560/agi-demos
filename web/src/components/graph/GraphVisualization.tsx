import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react';

import { Network, MousePointer2, Move, Focus, Plus, Minus, X } from 'lucide-react';

import { useMemoryStore } from '../../stores/memory';
import { useProjectStore } from '../../stores/project';
import { useThemeStore } from '../../stores/theme';

interface GraphVisualizationProps {
  width?: number;
  height?: number;
  showControls?: boolean;
}

interface GraphNode {
  id: string;
  label: string;
  type: string;
  x?: number;
  y?: number;
  size?: number;
  color?: string;
  entity?: any;
}

interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
  type?: string;
  weight?: number;
  color?: string;
  relationship?: any;
}

const getNodeColor = (type: string): string => {
  const colors: Record<string, string> = {
    person: '#3B82F6', // blue
    organization: '#10B981', // green
    location: '#F59E0B', // yellow
    event: '#EF4444', // red
    concept: '#8B5CF6', // purple
    object: '#6B7280', // gray
  };
  return colors[type] || '#6B7280';
};

const getEdgeColor = (type: string): string => {
  const colors: Record<string, string> = {
    works_at: '#3B82F6',
    located_in: '#10B981',
    part_of: '#F59E0B',
    knows: '#EF4444',
    related_to: '#8B5CF6',
    owns: '#6B7280',
  };
  return colors[type] || '#9CA3AF';
};

export const GraphVisualization: React.FC<GraphVisualizationProps> = ({
  width = 800,
  height = 600,
  showControls: _showControls = true,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const { currentProject } = useProjectStore();
  const { graphData, getGraphData, isLoading: _isLoading } = useMemoryStore();
  const { computedTheme } = useThemeStore();

  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [filterTypes, setFilterTypes] = useState<string[]>([]);
  const [showLabels, _setShowLabels] = useState(true);
  const [interactionMode, setInteractionMode] = useState<'select' | 'pan'>('select');

  // Auto-resize support
  const [dimensions, setDimensions] = useState({ width, height });

  useEffect(() => {
    if (containerRef.current) {
      setDimensions({
        width: containerRef.current.clientWidth,
        height: containerRef.current.clientHeight || height,
      });
    }
  }, [width, height]);

  const nodes: GraphNode[] = useMemo(
    () =>
      graphData?.entities.map((entity: any) => ({
        id: entity.id,
        label: entity.name,
        type: entity.type,
        size: 20 + (entity.importance || 1) * 5,
        color: getNodeColor(entity.type),
        entity,
      })) || [],
    [graphData]
  );

  const edges: GraphEdge[] = useMemo(
    () =>
      graphData?.relationships.map((relationship: any) => ({
        id: relationship.id,
        source: relationship.source_entity_id,
        target: relationship.target_entity_id,
        label: relationship.type,
        type: relationship.type,
        weight: relationship.weight || 1,
        color: getEdgeColor(relationship.type),
        relationship,
      })) || [],
    [graphData]
  );

  const loadGraphData = useCallback(async () => {
    if (!currentProject) return;

    try {
      await getGraphData(currentProject.id, { limit: 100 });
    } catch (error) {
      console.error('Failed to load graph data:', error);
    }
  }, [currentProject, getGraphData]);

  useEffect(() => {
    if (currentProject) {
      loadGraphData();
    }
  }, [currentProject, loadGraphData]);

  const drawGraph = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const isDark = computedTheme === 'dark' || true; // Force dark for now to match design visual

    // Clear canvas
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Apply transformations
    ctx.save();
    ctx.translate(offset.x, offset.y);
    ctx.scale(scale, scale);

    // Filter nodes and edges based on type filters
    const filteredNodes =
      filterTypes.length > 0 ? nodes.filter((node) => filterTypes.includes(node.type)) : nodes;

    const filteredNodeIds = new Set(filteredNodes.map((n) => n.id));
    const filteredEdges = edges.filter(
      (edge) => filteredNodeIds.has(edge.source) && filteredNodeIds.has(edge.target)
    );

    // Draw edges
    filteredEdges.forEach((edge) => {
      const sourceNode = nodes.find((n) => n.id === edge.source);
      const targetNode = nodes.find((n) => n.id === edge.target);

      if (!sourceNode || !targetNode) return;

      ctx.beginPath();
      ctx.moveTo(sourceNode.x || 0, sourceNode.y || 0);
      ctx.lineTo(targetNode.x || 0, targetNode.y || 0);
      ctx.strokeStyle = edge.color || (isDark ? '#4B5563' : '#9CA3AF');
      ctx.lineWidth = (edge.weight || 1) * 2;
      ctx.stroke();

      // Draw edge label
      if (showLabels && edge.label) {
        const midX = ((sourceNode.x || 0) + (targetNode.x || 0)) / 2;
        const midY = ((sourceNode.y || 0) + (targetNode.y || 0)) / 2;

        // Label Background
        ctx.fillStyle = isDark ? '#111521' : '#FFFFFF';
        const textWidth = ctx.measureText(edge.label).width;
        ctx.fillRect(midX - textWidth / 2 - 4, midY - 14, textWidth + 8, 18);

        ctx.fillStyle = isDark ? '#9CA3AF' : '#374151';
        ctx.font = '10px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(edge.label, midX, midY - 2);
      }
    });

    // Draw nodes
    filteredNodes.forEach((node) => {
      const x = node.x || 0;
      const y = node.y || 0;
      const size = node.size || 20;

      // Glow effect for selected
      if (selectedNode?.id === node.id) {
        ctx.beginPath();
        ctx.arc(x, y, size + 10, 0, 2 * Math.PI);
        ctx.fillStyle = `${node.color}33`; // 20% opacity
        ctx.fill();
      }

      // Draw node circle
      ctx.beginPath();
      ctx.arc(x, y, size, 0, 2 * Math.PI);
      ctx.fillStyle = node.color || '#6B7280';
      ctx.fill();

      // Border
      ctx.strokeStyle = isDark ? '#1F2937' : '#FFFFFF';
      ctx.lineWidth = 2;
      ctx.stroke();

      // Draw node label
      if (showLabels) {
        ctx.fillStyle = isDark ? '#E5E7EB' : '#1F2937';
        ctx.font = 'bold 12px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(node.label, x, y + size + 16);

        ctx.fillStyle = isDark ? '#9CA3AF' : '#6B7280';
        ctx.font = '10px Inter, sans-serif';
        ctx.fillText(node.type.toUpperCase(), x, y + size + 28);
      }
    });

    ctx.restore();
  }, [nodes, edges, scale, offset, showLabels, filterTypes, selectedNode, computedTheme]);

  useEffect(() => {
    drawGraph();
  }, [drawGraph, dimensions]);

  const handleMouseDown = (e: React.MouseEvent) => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const rect = canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left - offset.x) / scale;
    const y = (e.clientY - rect.top - offset.y) / scale;

    // Check if clicking on a node
    const clickedNode = nodes.find((node) => {
      const dx = (node.x || 0) - x;
      const dy = (node.y || 0) - y;
      const distance = Math.sqrt(dx * dx + dy * dy);
      return distance <= (node.size || 20);
    });

    if (clickedNode && interactionMode === 'select') {
      setSelectedNode(clickedNode);
    } else {
      setIsDragging(true);
      setDragStart({ x: e.clientX - offset.x, y: e.clientY - offset.y });
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging) return;

    setOffset({
      x: e.clientX - dragStart.x,
      y: e.clientY - dragStart.y,
    });
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  const handleZoomIn = () => {
    setScale((prev) => Math.min(prev * 1.2, 3));
  };

  const handleZoomOut = () => {
    setScale((prev) => Math.max(prev / 1.2, 0.1));
  };

  const handleResetView = () => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
    setSelectedNode(null);
  };

  // Memoize availableTypes to avoid recalculating on every render (rerender-memo)
  const availableTypes = useMemo(
    () => Array.from(new Set(nodes.map((node) => node.type))),
    [nodes]
  );

  if (!currentProject) {
    return (
      <div className="bg-[#111521] rounded-lg shadow-sm border border-slate-800 p-8 h-full">
        <div className="text-center">
          <Network className="h-12 w-12 text-slate-600 mx-auto mb-3" />
          <h3 className="text-lg font-medium text-white mb-2">Please select a project</h3>
        </div>
      </div>
    );
  }

  return (
    <div
      className="bg-[#111521] rounded-lg shadow-sm border border-slate-800 relative h-full flex flex-col overflow-hidden"
      ref={containerRef}
    >
      {/* Grid Pattern Background */}
      <div
        className="absolute inset-0 opacity-20 pointer-events-none"
        style={{
          backgroundImage: 'radial-gradient(#2b324a 1px, transparent 1px)',
          backgroundSize: '40px 40px',
        }}
      ></div>

      {/* Floating Toolbar (Left) */}
      <div className="absolute top-6 left-6 flex flex-col gap-2 z-10">
        <div className="bg-[#1e2332] border border-slate-700 rounded-lg shadow-xl overflow-hidden flex flex-col">
          <button
            onClick={() => setInteractionMode('select')}
            className={`p-2.5 hover:bg-slate-700 border-b border-slate-700 transition-colors ${interactionMode === 'select' ? 'text-white bg-slate-700' : 'text-slate-400'}`}
            title="Select Tool"
          >
            <MousePointer2 className="w-5 h-5" />
          </button>
          <button
            onClick={() => setInteractionMode('pan')}
            className={`p-2.5 hover:bg-slate-700 transition-colors ${interactionMode === 'pan' ? 'text-white bg-slate-700' : 'text-slate-400'}`}
            title="Pan Tool"
          >
            <Move className="w-5 h-5" />
          </button>
        </div>
        <div className="bg-[#1e2332] border border-slate-700 rounded-lg shadow-xl overflow-hidden flex flex-col mt-2">
          <button
            onClick={handleZoomIn}
            className="p-2.5 text-slate-400 hover:text-white hover:bg-slate-700 border-b border-slate-700 transition-colors"
          >
            <Plus className="w-5 h-5" />
          </button>
          <button
            onClick={handleZoomOut}
            className="p-2.5 text-slate-400 hover:text-white hover:bg-slate-700 transition-colors"
          >
            <Minus className="w-5 h-5" />
          </button>
        </div>
        <button
          onClick={handleResetView}
          className="bg-[#1e2332] border border-slate-700 rounded-lg shadow-xl p-2.5 text-slate-400 hover:text-white hover:bg-slate-700 mt-2 transition-colors"
        >
          <Focus className="w-5 h-5" />
        </button>
      </div>

      {/* Legend / Filters (Bottom Left) */}
      <div className="absolute bottom-6 left-6 z-10">
        <div className="bg-[#1e2332]/90 backdrop-blur border border-slate-700 rounded-lg p-3 shadow-xl">
          <div className="text-xs font-bold text-slate-400 mb-2 uppercase tracking-wider">
            Entity Types
          </div>
          <div className="flex flex-col gap-2">
            {availableTypes.map((type) => (
              <label
                key={type}
                className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer hover:text-white"
              >
                <input
                  type="checkbox"
                  checked={!filterTypes.includes(type)}
                  onChange={() => {
                    setFilterTypes((prev) =>
                      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type]
                    );
                  }}
                  className="rounded border-slate-600 bg-slate-800 text-blue-600 focus:ring-0 w-3 h-3"
                />
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: getNodeColor(type) }}
                ></span>
                <span className="capitalize">{type}</span>
              </label>
            ))}
          </div>
        </div>
      </div>

      {/* Canvas */}
      <div className="flex-1 relative cursor-grab active:cursor-grabbing">
        <canvas
          ref={canvasRef}
          width={dimensions.width}
          height={dimensions.height}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
          className="w-full h-full block"
        />
      </div>

      {/* Node Details Panel (Right) */}
      {selectedNode && (
        <div className="absolute top-6 right-6 bottom-6 w-80 bg-[#1e2332] border border-slate-700 shadow-2xl rounded-xl z-20 flex flex-col overflow-hidden animate-in slide-in-from-right duration-300">
          <div className="p-5 border-b border-slate-700 bg-gradient-to-r from-blue-900/20 to-transparent">
            <div className="flex justify-between items-start mb-2">
              <div className="bg-blue-500/20 text-blue-300 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide border border-blue-500/30">
                {selectedNode.type}
              </div>
              <button
                onClick={() => setSelectedNode(null)}
                className="text-slate-400 hover:text-white transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <h2 className="text-xl font-bold text-white leading-tight break-words">
              {selectedNode.label}
            </h2>
            <div className="flex items-center gap-2 mt-2 text-xs text-slate-400">
              <span className="font-mono">ID: {selectedNode.id.substring(0, 8)}</span>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-5 space-y-6">
            <div>
              <div className="flex justify-between items-end mb-1">
                <label className="text-xs font-semibold text-slate-400 uppercase">
                  Impact Score
                </label>
                <span className="text-emerald-400 font-bold text-sm">
                  {(selectedNode.entity.importance || 1) * 10}/100
                </span>
              </div>
              <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                <div
                  className="bg-gradient-to-r from-emerald-500 to-blue-600 h-full rounded-full"
                  style={{ width: `${(selectedNode.entity.importance || 1) * 10}%` }}
                ></div>
              </div>
            </div>
            <div>
              <label className="text-xs font-semibold text-slate-400 uppercase mb-2 block">
                Description
              </label>
              <p className="text-sm text-slate-300 leading-relaxed">
                {selectedNode.entity.description || 'No description available.'}
              </p>
            </div>
            <div>
              <div className="flex justify-between items-center mb-3">
                <label className="text-xs font-semibold text-slate-400 uppercase">Attributes</label>
              </div>
              <div className="space-y-2">
                {Object.entries(selectedNode.entity.metadata || {}).map(
                  ([key, val]: [string, any]) => (
                    <div key={key} className="flex justify-between text-sm">
                      <span className="text-slate-500 capitalize">{key.replace('_', ' ')}:</span>
                      <span className="text-slate-300">{String(val)}</span>
                    </div>
                  )
                )}
              </div>
            </div>
          </div>
          <div className="p-4 border-t border-slate-700 bg-[#151820] flex gap-2">
            <button className="flex-1 py-2 rounded-lg border border-slate-600 bg-[#1e2332] text-slate-300 text-sm font-medium hover:bg-slate-700 hover:text-white transition-colors">
              Expand
            </button>
            <button className="flex-1 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 shadow-lg shadow-blue-600/20 transition-colors">
              Edit Node
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
