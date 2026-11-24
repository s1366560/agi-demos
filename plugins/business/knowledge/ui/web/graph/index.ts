/**
 * Graph Components Barrel Export
 *
 * Components for knowledge graph visualization:
 * - CytoscapeGraph: Cytoscape.js-based graph renderer (refactored with composite pattern)
 */

export { CytoscapeGraph } from './CytoscapeGraph';

// Re-export types from refactored CytoscapeGraph
export type {
  GraphConfig,
  NodeData,
  ViewportProps,
  NodeInfoPanelProps,
  CytoscapeGraphProps,
  LegacyCytoscapeGraphProps,
} from './CytoscapeGraph/types';
