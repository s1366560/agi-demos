/**
 * CytoscapeGraph Viewport Component
 *
 * Handles the actual Cytoscape.js rendering and graph visualization.
 */

import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react';

import { useThemeStore } from '@/stores/theme';

import { graphService } from '@/services/graphService';

import { toCytoscapeLayoutOptions, generateCytoscapeStyles, THEME_COLORS } from './Config';

import type { GraphConfig, NodeData, CytoscapeElement } from './types';

// ========================================
// Loading State Component
// ========================================

const ViewportLoading: React.FC = () => (
  <div className="flex-1 flex items-center justify-center">
    <div className="text-center">
      <span className="material-symbols-outlined text-4xl text-blue-600 animate-spin">
        progress_activity
      </span>
      <p className="text-slate-600 dark:text-slate-400 mt-2">Loading graph visualization...</p>
    </div>
  </div>
);

// ========================================
// Props
// ========================================

interface ViewportProps {
  config: GraphConfig;
  onNodeClick?: ((node: NodeData | null) => void) | undefined;
  onStateChange?:
    | ((state: {
        nodeCount: number;
        edgeCount: number;
        loading: boolean;
        error: string | null;
      }) => void)
    | undefined;
  setCyInstance?: ((cy: any) => void) | undefined;
  onNodeSelect?: ((node: NodeData | null) => void) | undefined;
}

// ========================================
// Main Viewport Component
// ========================================

export function CytoscapeGraphViewport({
  config,
  onNodeClick,
  onStateChange,
  setCyInstance,
  onNodeSelect,
}: ViewportProps) {
  const { computedTheme } = useThemeStore();
  const currentTheme = THEME_COLORS[computedTheme];
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<any>(null);

  // Dynamic import state for cytoscape (bundle-dynamic-imports)
  const [CytoscapeLib, setCytoscapeLib] = useState<any>(null);
  const [loadingLib, setLoadingLib] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nodeCount, setNodeCount] = useState(0);
  const [edgeCount, setEdgeCount] = useState(0);
  const onNodeClickRef = useRef(onNodeClick);

  useEffect(() => {
    onNodeClickRef.current = onNodeClick;
  }, [onNodeClick]);

  // Dynamic import cytoscape
  useEffect(() => {
    let mounted = true;
    import('cytoscape').then((mod) => {
      if (mounted) {
        setCytoscapeLib(() => mod);
        setLoadingLib(false);
      }
    });
    return () => {
      mounted = false;
    };
  }, []);

  // Generate styles based on theme
  const cytoscapeStyles = useMemo(() => {
    return generateCytoscapeStyles(currentTheme, computedTheme === 'dark');
  }, [computedTheme, currentTheme]);

  // Notify parent of state changes
  useEffect(() => {
    onStateChange?.({ nodeCount, edgeCount, loading, error });
  }, [nodeCount, edgeCount, loading, error, onStateChange]);

  // Load Graph Data
  const loadGraphData = useCallback(async () => {
    if (!cyRef.current) return;

    setLoading(true);
    setError(null);

    try {
      let data;
      if (config.data.subgraphNodeIds && config.data.subgraphNodeIds.length > 0) {
        data = await graphService.getSubgraph({
          node_uuids: config.data.subgraphNodeIds,
          include_neighbors: true,
          limit: 500,
          tenant_id: config.data.tenantId,
          project_id: config.data.projectId,
        });
      } else {
        data = await graphService.getGraphData({
          tenant_id: config.data.tenantId,
          project_id: config.data.projectId,
          limit: 500,
        });
      }

      const elements: CytoscapeElement[] = [];

      // Nodes
      data.elements.nodes.forEach((node: any) => {
        const nodeType = node.data.label;

        if (config.data.includeCommunities === false && nodeType === 'Community') return;
        if (config.data.minConnections && config.data.minConnections > 0) {
          const connections = data.elements.edges.filter(
            (e: any) => e.data.source === node.data.id || e.data.target === node.data.id
          ).length;
          if (connections < config.data.minConnections) return;
        }

        elements.push({
          group: 'nodes',
          data: {
            id: node.data.id,
            label: nodeType,
            name: node.data.name || node.data.label,
            type: nodeType,
            uuid: node.data.uuid,
            summary: node.data.summary,
            entity_type: node.data.entity_type,
            member_count: node.data.member_count,
            tenant_id: node.data.tenant_id,
            project_id: node.data.project_id,
          },
        });
      });

      // Edges
      data.elements.edges.forEach((edge: any) => {
        elements.push({
          group: 'edges',
          data: {
            id: edge.data.id,
            source: edge.data.source,
            target: edge.data.target,
            label: edge.data.label || '',
          },
        });
      });

      // Clear existing elements and add new ones
      cyRef.current.elements().remove();
      cyRef.current.add(elements);

      const layoutOpts = toCytoscapeLayoutOptions(config.layout);
      cyRef.current.layout(layoutOpts).run();

      setNodeCount(elements.filter((e: CytoscapeElement) => e.group === 'nodes').length);
      setEdgeCount(elements.filter((e: CytoscapeElement) => e.group === 'edges').length);
    } catch (err) {
      console.error('Failed to load graph data:', err);
      setError('Failed to load graph data');
    } finally {
      setLoading(false);
    }
  }, [config]);

  // Initialize Cytoscape
  useEffect(() => {
    if (!containerRef.current || !CytoscapeLib) return;

    const { cytoscape } = CytoscapeLib;

    const cy = cytoscape({
      container: containerRef.current,
      style: cytoscapeStyles,
      minZoom: 0.1,
      maxZoom: 3,
      wheelSensitivity: 0.2,
    });

    cyRef.current = cy;
    setCyInstance?.(cy);

    const handleNodeTap = (evt: any) => {
      const node = evt.target;
      const nodeData: NodeData = node.data();
      onNodeClickRef.current?.(nodeData);
      onNodeSelect?.(nodeData);
    };

    const handleBackgroundTap = () => {
      onNodeClickRef.current?.(null);
      onNodeSelect?.(null);
    };

    cy.on('tap', 'node', handleNodeTap);
    cy.on('tap', handleBackgroundTap);
    cy.boxSelectionEnabled(true);

    // Listen for reload event
    const handleReload = () => {
      loadGraphData();
    };
    window.addEventListener('cytoscape-reload', handleReload);

    return () => {
      window.removeEventListener('cytoscape-reload', handleReload);
      cy.destroy();
    };
  }, [CytoscapeLib, onNodeSelect, setCyInstance, cytoscapeStyles, loadGraphData]);

  // Update styles when theme changes
  useEffect(() => {
    if (cyRef.current) {
      cyRef.current.style(cytoscapeStyles);
    }
  }, [cytoscapeStyles]);

  // Load data when dependencies change
  useEffect(() => {
    if (cyRef.current && CytoscapeLib) {
      loadGraphData();
    }
  }, [loadGraphData, CytoscapeLib]);

  if (loadingLib || !CytoscapeLib) {
    return <ViewportLoading />;
  }

  return (
    <div className="flex-1 relative">
      {loading && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm">
          <div className="text-center">
            <span className="material-symbols-outlined text-4xl text-blue-600 animate-spin">
              progress_activity
            </span>
            <p className="text-slate-600 dark:text-slate-400 mt-2">Loading graph...</p>
          </div>
        </div>
      )}

      {error && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm">
          <div className="text-center">
            <span className="material-symbols-outlined text-4xl text-red-600">error</span>
            <p className="text-slate-600 dark:text-slate-400 mt-2">{error}</p>
            <button
              onClick={loadGraphData}
              className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-500"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      <div
        ref={containerRef}
        className="w-full h-full"
        style={{ backgroundColor: currentTheme.background }}
      />
    </div>
  );
}

CytoscapeGraphViewport.displayName = 'CytoscapeGraphViewport';
