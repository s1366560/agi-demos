/**
 * CytoscapeGraph Component - Composite Component Pattern
 *
 * Provides flexible knowledge graph visualization using Cytoscape.js.
 * Supports three usage patterns:
 * 1. Config Object API: <CytoscapeGraph config={graphConfig} />
 * 2. Composite Component API: <CytoscapeGraph><CytoscapeGraph.Viewport /></CytoscapeGraph>
 * 3. Legacy API (backward compatible): <CytoscapeGraph projectId="p1" />
 */

export { CytoscapeGraph } from './CytoscapeGraph';
export type { GraphConfig, NodeData, ViewportProps, NodeInfoPanelProps } from './types';
