/**
 * CytoscapeGraph Viewport Component
 *
 * Handles the actual Cytoscape.js rendering and graph visualization.
 */

import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import { Loader2, AlertCircle } from 'lucide-react';

import { useThemeStore } from '@/stores/theme';

import { graphService } from '@/services/graphService';
import type { GraphData, GraphEdge, GraphNode } from '@/services/graphService';

import { toCytoscapeLayoutOptions, generateCytoscapeStyles, THEME_COLORS } from './Config';

import type { GraphConfig, NodeData } from './types';
import type cytoscape from 'cytoscape';

type CytoscapeFactory = (options?: cytoscape.CytoscapeOptions) => cytoscape.Core;
type CytoscapeNodeType = NodeData['type'];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isCytoscapeFactory(value: unknown): value is CytoscapeFactory {
  return typeof value === 'function';
}

function resolveCytoscapeFactory(moduleValue: unknown): CytoscapeFactory | null {
  if (isCytoscapeFactory(moduleValue)) {
    return moduleValue;
  }

  if (!isRecord(moduleValue)) {
    return null;
  }

  if (isCytoscapeFactory(moduleValue.default)) {
    return moduleValue.default;
  }

  if (isCytoscapeFactory(moduleValue.cytoscape)) {
    return moduleValue.cytoscape;
  }

  return null;
}

function toNodeType(value: string | undefined): CytoscapeNodeType | null {
  if (value === 'Entity' || value === 'Episodic' || value === 'Community') {
    return value;
  }

  return null;
}

function getNodeType(node: GraphNode): CytoscapeNodeType {
  return toNodeType(node.label) ?? toNodeType(node.type) ?? 'Entity';
}

function getNodeName(node: GraphNode): string {
  return node.name || node.label || node.id;
}

function edgeTouchesNode(edge: GraphEdge, nodeId: string): boolean {
  return edge.source === nodeId || edge.target === nodeId;
}

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }

  if (typeof error === 'string' && error.trim()) {
    return error;
  }

  return fallback;
}

// ========================================
// Loading State Component
// ========================================

const ViewportLoading: React.FC = () => {
  const { t } = useTranslation();

  return (
    <div className="flex min-h-[420px] flex-1 items-center justify-center">
      <div className="text-center">
        <Loader2
          size={36}
          className="text-blue-600 animate-spin motion-reduce:animate-none mx-auto"
        />
        <p className="text-slate-600 dark:text-slate-400 mt-2">
          {t('graph.cytoscapeViewport.loadingVisualization', {
            defaultValue: 'Loading graph visualization...',
          })}
        </p>
      </div>
    </div>
  );
};

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
  setCyInstance?: ((cy: cytoscape.Core) => void) | undefined;
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
  const { t } = useTranslation();
  const { computedTheme } = useThemeStore();
  const currentTheme = THEME_COLORS[computedTheme];
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const activeLayoutRef = useRef<cytoscape.Layouts | null>(null);
  const isMountedRef = useRef(true);
  const loadGraphDataRef = useRef<(() => Promise<void>) | null>(null);

  // Dynamic import state for cytoscape (bundle-dynamic-imports)
  const [cytoscapeFactory, setCytoscapeFactory] = useState<CytoscapeFactory | null>(null);
  const [loadingLib, setLoadingLib] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nodeCount, setNodeCount] = useState(0);
  const [edgeCount, setEdgeCount] = useState(0);
  const onNodeClickRef = useRef(onNodeClick);

  useEffect(() => {
    onNodeClickRef.current = onNodeClick;
  }, [onNodeClick]);

  useEffect(() => {
    isMountedRef.current = true;

    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // Dynamic import cytoscape
  useEffect(() => {
    let mounted = true;
    void import('cytoscape')
      .then((mod: unknown) => {
        if (!mounted) {
          return;
        }

        const factory = resolveCytoscapeFactory(mod);
        if (factory) {
          setCytoscapeFactory(() => factory);
        } else {
          setError(
            t('graph.cytoscapeViewport.initializeFailed', {
              defaultValue: 'Failed to initialize graph visualization',
            })
          );
        }
        setLoadingLib(false);
      })
      .catch((err: unknown) => {
        if (mounted) {
          console.error('Failed to load graph renderer:', err);
          setError(
            t('graph.cytoscapeViewport.initializeFailed', {
              defaultValue: 'Failed to initialize graph visualization',
            })
          );
          setLoadingLib(false);
        }
      });
    return () => {
      mounted = false;
    };
  }, [t]);

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
    setLoading(true);
    setError(null);

    try {
      let data: GraphData;
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

      const elements: cytoscape.ElementDefinition[] = [];

      // Nodes
      data.elements.nodes.forEach(({ data: node }) => {
        const nodeType = getNodeType(node);
        const connectionCount = data.elements.edges.filter(({ data: edge }) =>
          edgeTouchesNode(edge, node.id)
        ).length;

        if (config.data.includeCommunities === false && nodeType === 'Community') return;
        if (config.data.minConnections && config.data.minConnections > 0) {
          if (connectionCount < config.data.minConnections) return;
        }

        elements.push({
          group: 'nodes',
          data: {
            id: node.id,
            label: nodeType,
            name: getNodeName(node),
            type: nodeType,
            uuid: node.uuid,
            summary: node.summary,
            entity_type: node.entity_type,
            member_count: node.member_count,
            connection_count: connectionCount,
            tenant_id: node.tenant_id,
            project_id: node.project_id,
          },
        });
      });

      // Edges
      data.elements.edges.forEach(({ data: edge }) => {
        elements.push({
          group: 'edges',
          data: {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            label: edge.label || '',
          },
        });
      });

      const cy = cyRef.current;
      if (!isMountedRef.current || !cy || cy.destroyed()) {
        return;
      }

      // Clear existing elements and add new ones
      cy.elements().remove();
      cy.add(elements);

      const layoutOpts = {
        ...toCytoscapeLayoutOptions(config.layout),
        animate: false,
      };
      activeLayoutRef.current?.stop();
      const layout = cy.layout(layoutOpts);
      activeLayoutRef.current = layout;
      layout.run();

      const nextNodeCount = elements.filter((element) => element.group === 'nodes').length;
      const nextEdgeCount = elements.filter((element) => element.group === 'edges').length;

      setNodeCount((current) => (current === nextNodeCount ? current : nextNodeCount));
      setEdgeCount((current) => (current === nextEdgeCount ? current : nextEdgeCount));
    } catch (err) {
      console.error('Failed to load graph data:', err);
      const fallbackMessage = t('graph.cytoscapeViewport.loadDataFailed', {
        defaultValue: 'Failed to load graph data',
      });
      if (isMountedRef.current) {
        setError(getErrorMessage(err, fallbackMessage));
      }
    } finally {
      if (isMountedRef.current) {
        setLoading(false);
      }
    }
  }, [config, t]);

  useEffect(() => {
    loadGraphDataRef.current = loadGraphData;
  }, [loadGraphData]);

  // Initialize Cytoscape
  useEffect(() => {
    if (!containerRef.current || !cytoscapeFactory) return;

    let cy: cytoscape.Core;
    try {
      cy = cytoscapeFactory({
        container: containerRef.current,
        style: cytoscapeStyles as cytoscape.StylesheetJson,
        layout: { name: 'preset' },
        minZoom: 0.1,
        maxZoom: 3,
      });
    } catch (err) {
      console.error('Failed to initialize graph visualization:', err);
      setError(
        t('graph.cytoscapeViewport.initializeFailed', {
          defaultValue: 'Failed to initialize graph visualization',
        })
      );
      setLoading(false);
      return;
    }

    cyRef.current = cy;
    setCyInstance?.(cy);

    const handleNodeTap = (evt: cytoscape.EventObjectNode) => {
      const nodeData = evt.target.data() as unknown as NodeData;
      onNodeClickRef.current?.(nodeData);
      onNodeSelect?.(nodeData);
    };

    const handleBackgroundTap = (evt: cytoscape.EventObject) => {
      if (evt.target !== cy) {
        return;
      }
      onNodeClickRef.current?.(null);
      onNodeSelect?.(null);
    };

    cy.on('tap', 'node', handleNodeTap);
    cy.on('tap', handleBackgroundTap);
    cy.boxSelectionEnabled(true);

    // Listen for reload event
    const handleReload = () => {
      void loadGraphDataRef.current?.();
    };
    window.addEventListener('cytoscape-reload', handleReload);

    return () => {
      window.removeEventListener('cytoscape-reload', handleReload);
      activeLayoutRef.current?.stop();
      activeLayoutRef.current = null;
      cy.off('tap', 'node', handleNodeTap);
      cy.off('tap', handleBackgroundTap);
      if (cyRef.current === cy) {
        cyRef.current = null;
      }
      cy.stop(true, true);
      cy.destroy();
    };
  }, [cytoscapeFactory, onNodeSelect, setCyInstance, cytoscapeStyles, t]);

  // Update styles when theme changes
  useEffect(() => {
    if (cyRef.current) {
      cyRef.current.style(cytoscapeStyles);
    }
  }, [cytoscapeStyles]);

  // Load data when dependencies change
  useEffect(() => {
    if (cyRef.current && cytoscapeFactory) {
      void loadGraphData();
    }
  }, [loadGraphData, cytoscapeFactory]);

  if (loadingLib || !cytoscapeFactory) {
    return <ViewportLoading />;
  }

  return (
    <div className="relative min-h-[420px] flex-1">
      {loading && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/90 dark:bg-slate-900/90">
          <div className="text-center">
            <Loader2
              size={36}
              className="text-blue-600 animate-spin motion-reduce:animate-none mx-auto"
            />
            <p className="text-slate-600 dark:text-slate-400 mt-2">
              {t('graph.cytoscapeViewport.loadingGraph', { defaultValue: 'Loading graph...' })}
            </p>
          </div>
        </div>
      )}

      {error && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/90 dark:bg-slate-900/90">
          <div className="text-center">
            <AlertCircle size={36} className="text-red-600 mx-auto" />
            <p className="text-slate-600 dark:text-slate-400 mt-2">{error}</p>
            <button
              type="button"
              onClick={() => {
                void loadGraphData();
              }}
              className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-500"
            >
              {t('common.retry', { defaultValue: 'Retry' })}
            </button>
          </div>
        </div>
      )}

      <div
        ref={containerRef}
        className="h-full min-h-[420px] w-full"
        style={{ backgroundColor: currentTheme.background }}
      />
    </div>
  );
}

CytoscapeGraphViewport.displayName = 'CytoscapeGraphViewport';
