/**
 * CytoscapeGraph Component Type Definitions
 *
 * Provides type definitions for the refactored CytoscapeGraph component
 * supporting both config object API and composite component pattern.
 */

// ========================================
// Core Types
// ========================================

/**
 * Node data structure returned by the graph service
 */
export interface NodeData {
  id: string;
  uuid?: string | undefined;
  name: string;
  type: 'Entity' | 'Episodic' | 'Community';
  label?: string | undefined;
  summary?: string | undefined;
  entity_type?: string | undefined;
  member_count?: number | undefined;
  tenant_id?: string | undefined;
  project_id?: string | undefined;
  created_at?: string | undefined;
  [key: string]: unknown;
}

/**
 * Edge data structure returned by the graph service
 */
export interface EdgeData {
  id: string;
  source: string;
  target: string;
  label?: string | undefined;
  weight?: number | undefined;
  [key: string]: unknown;
}

// ========================================
// Config Types
// ========================================

/**
 * Data loading configuration
 */
export interface GraphDataConfig {
  /** Project ID for data scoping */
  projectId?: string | undefined;
  /** Tenant ID for multi-tenant support */
  tenantId?: string | undefined;
  /** Include community nodes in the graph */
  includeCommunities?: boolean | undefined;
  /** Minimum number of connections for a node to be displayed */
  minConnections?: number | undefined;
  /** Specific node IDs to load as a subgraph */
  subgraphNodeIds?: string[] | undefined;
}

/**
 * Feature flags for graph UI elements
 */
export interface GraphFeatureConfig {
  /** Show toolbar with actions */
  showToolbar?: boolean | undefined;
  /** Show legend at the bottom */
  showLegend?: boolean | undefined;
  /** Show stats (node/edge counts) */
  showStats?: boolean | undefined;
  /** Enable export functionality */
  enableExport?: boolean | undefined;
  /** Enable relayout button */
  enableRelayout?: boolean | undefined;
}

/**
 * Layout configuration options
 */
export interface GraphLayoutConfig {
  /** Layout algorithm: 'cose' | 'circle' | 'concentric' | 'grid' */
  type?: 'cose' | 'circle' | 'concentric' | 'grid' | 'breadthfirst' | 'random' | undefined;
  /** Animate layout transitions */
  animate?: boolean | undefined;
  /** Animation duration in milliseconds */
  animationDuration?: number | undefined;
  /** Animation easing function */
  animationEasing?: string | undefined;
  /** Ideal edge length for force-directed layouts */
  idealEdgeLength?: number | undefined;
  /** Node overlap amount */
  nodeOverlap?: number | undefined;
  /** Component spacing */
  componentSpacing?: number | undefined;
  /** Gravity for force-directed layouts */
  gravity?: number | undefined;
  /** Number of iterations */
  numIter?: number | undefined;
  /** Initial temperature */
  initialTemp?: number | undefined;
  /** Cooling factor */
  coolingFactor?: number | undefined;
  /** Minimum temperature */
  minTemp?: number | undefined;
}

/**
 * Theme color configuration
 */
export interface GraphThemeConfig {
  background?: string | undefined;
  nodeBorder?: string | undefined;
  edgeLine?: string | undefined;
  edgeLabel?: string | undefined;
  colors?: {
    episodic?: string | undefined;
    community?: string | undefined;
    person?: string | undefined;
    organization?: string | undefined;
    location?: string | undefined;
    event?: string | undefined;
    product?: string | undefined;
    default?: string | undefined;
  } | undefined;
}

/**
 * Complete graph configuration object
 */
export interface GraphConfig {
  /** Data loading configuration */
  data: GraphDataConfig;
  /** Feature flags */
  features?: GraphFeatureConfig | undefined;
  /** Layout configuration */
  layout?: GraphLayoutConfig | undefined;
  /** Custom theme overrides */
  theme?: GraphThemeConfig | undefined;
}

// ========================================
// Component Props Types
// ========================================

/**
 * Props for the root CytoscapeGraph component (config API)
 */
export interface CytoscapeGraphProps {
  /** Configuration object */
  config?: GraphConfig | undefined;
  /** Children for composite component pattern */
  children?: React.ReactNode | undefined;
}

/**
 * Props for the Viewport subcomponent
 */
export interface ViewportProps {
  /** Project ID for data scoping */
  projectId?: string | undefined;
  /** Tenant ID for multi-tenant support */
  tenantId?: string | undefined;
  /** Include community nodes */
  includeCommunities?: boolean | undefined;
  /** Minimum connections threshold */
  minConnections?: number | undefined;
  /** Specific node IDs for subgraph */
  subgraphNodeIds?: string[] | undefined;
  /** Node click callback */
  onNodeClick?: ((node: NodeData | null) => void) | undefined;
  /** Highlight specific nodes */
  highlightNodeIds?: string[] | undefined;
}

/**
 * Props for the Controls subcomponent
 */
export interface ControlsProps {
  /** Additional CSS class name */
  className?: string | undefined;
  /** Custom render for toolbar content */
  renderCustom?: React.ReactNode | undefined;
}

/**
 * Props for the NodeInfoPanel subcomponent
 */
export interface NodeInfoPanelProps {
  /** Currently selected node data */
  node: NodeData | null;
  /** Close callback */
  onClose?: (() => void) | undefined;
  /** Panel position: 'right' | 'left' | 'float' */
  position?: 'right' | 'left' | 'float' | undefined;
  /** Additional CSS class name */
  className?: string | undefined;
}

/**
 * Props for the Stats subcomponent (optional)
 */
export interface StatsProps {
  /** Node count */
  nodeCount?: number | undefined;
  /** Edge count */
  edgeCount?: number | undefined;
  /** Loading state */
  loading?: boolean | undefined;
}

/**
 * Props for the Legend subcomponent (optional)
 */
export interface LegendProps {
  /** Include communities in legend */
  includeCommunities?: boolean | undefined;
  /** Custom legend items */
  customItems?: Array<{ color: string; label: string; size?: string | undefined }> | undefined;
}

// ========================================
// Legacy Props (Backward Compatibility)
// ========================================

/**
 * Legacy props for backward compatibility
 */
export interface LegacyCytoscapeGraphProps {
  projectId?: string | undefined;
  tenantId?: string | undefined;
  includeCommunities?: boolean | undefined;
  minConnections?: number | undefined;
  onNodeClick?: ((node: NodeData | null) => void) | undefined;
  highlightNodeIds?: string[] | undefined;
  subgraphNodeIds?: string[] | undefined;
}

// ========================================
// Internal Types
// ========================================

/**
 * Cytoscape element representation
 */
export interface CytoscapeElement {
  group: 'nodes' | 'edges';
  data: Record<string, unknown>;
}

/**
 * Cytoscape style definition
 */
export interface CytoscapeStyle {
  selector: string;
  style: Record<string, unknown>;
}

/**
 * Graph state
 */
export interface GraphState {
  loading: boolean;
  error: string | null;
  nodeCount: number;
  edgeCount: number;
  selectedNode: NodeData | null;
}

/**
 * Graph actions
 */
export interface GraphActions {
  relayout: () => void;
  fitView: () => void;
  exportImage: () => void;
  reloadData: () => void;
  clearSelection: () => void;
}
