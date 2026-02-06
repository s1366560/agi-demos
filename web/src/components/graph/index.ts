/**
 * Graph Components Barrel Export
 *
 * Components for knowledge graph visualization:
 * - GraphVisualization: Main graph visualization component
 * - CytoscapeGraph: Cytoscape.js-based graph renderer (refactored with composite pattern)
 * - EntityCard: Entity detail card component
 */

export { GraphVisualization } from './GraphVisualization';
export { CytoscapeGraph } from './CytoscapeGraph';
export { EntityCard, getEntityTypeColor } from './EntityCard';
export type { Entity, EntityCardProps } from './EntityCard';

// Re-export types from refactored CytoscapeGraph
export type {
  GraphConfig,
  NodeData,
  ViewportProps,
  NodeInfoPanelProps,
  CytoscapeGraphProps,
  LegacyCytoscapeGraphProps,
} from './CytoscapeGraph/types';
