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
  uuid?: string;
  name: string;
  type: 'Entity' | 'Episodic' | 'Community';
  label?: string;
  summary?: string;
  entity_type?: string;
  member_count?: number;
  tenant_id?: string;
  project_id?: string;
  created_at?: string;
  [key: string]: unknown;
}

/**
 * Edge data structure returned by the graph service
 */
export interface EdgeData {
  id: string;
  source: string;
  target: string;
  label?: string;
  weight?: number;
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
  projectId?: string;
  /** Tenant ID for multi-tenant support */
  tenantId?: string;
  /** Include community nodes in the graph */
  includeCommunities?: boolean;
  /** Minimum number of connections for a node to be displayed */
  minConnections?: number;
  /** Specific node IDs to load as a subgraph */
  subgraphNodeIds?: string[];
}

/**
 * Feature flags for graph UI elements
 */
export interface GraphFeatureConfig {
  /** Show toolbar with actions */
  showToolbar?: boolean;
  /** Show legend at the bottom */
  showLegend?: boolean;
  /** Show stats (node/edge counts) */
  showStats?: boolean;
  /** Enable export functionality */
  enableExport?: boolean;
  /** Enable relayout button */
  enableRelayout?: boolean;
}

/**
 * Layout configuration options
 */
export interface GraphLayoutConfig {
  /** Layout algorithm: 'cose' | 'circle' | 'concentric' | 'grid' */
  type?: 'cose' | 'circle' | 'concentric' | 'grid' | 'breadthfirst' | 'random';
  /** Animate layout transitions */
  animate?: boolean;
  /** Animation duration in milliseconds */
  animationDuration?: number;
  /** Animation easing function */
  animationEasing?: string;
  /** Ideal edge length for force-directed layouts */
  idealEdgeLength?: number;
  /** Node overlap amount */
  nodeOverlap?: number;
  /** Component spacing */
  componentSpacing?: number;
  /** Gravity for force-directed layouts */
  gravity?: number;
  /** Number of iterations */
  numIter?: number;
  /** Initial temperature */
  initialTemp?: number;
  /** Cooling factor */
  coolingFactor?: number;
  /** Minimum temperature */
  minTemp?: number;
}

/**
 * Theme color configuration
 */
export interface GraphThemeConfig {
  background?: string;
  nodeBorder?: string;
  edgeLine?: string;
  edgeLabel?: string;
  colors?: {
    episodic?: string;
    community?: string;
    person?: string;
    organization?: string;
    location?: string;
    event?: string;
    product?: string;
    default?: string;
  };
}

/**
 * Complete graph configuration object
 */
export interface GraphConfig {
  /** Data loading configuration */
  data: GraphDataConfig;
  /** Feature flags */
  features?: GraphFeatureConfig;
  /** Layout configuration */
  layout?: GraphLayoutConfig;
  /** Custom theme overrides */
  theme?: GraphThemeConfig;
}

// ========================================
// Component Props Types
// ========================================

/**
 * Props for the root CytoscapeGraph component (config API)
 */
export interface CytoscapeGraphProps {
  /** Configuration object */
  config?: GraphConfig;
  /** Children for composite component pattern */
  children?: React.ReactNode;
}

/**
 * Props for the Viewport subcomponent
 */
export interface ViewportProps {
  /** Project ID for data scoping */
  projectId?: string;
  /** Tenant ID for multi-tenant support */
  tenantId?: string;
  /** Include community nodes */
  includeCommunities?: boolean;
  /** Minimum connections threshold */
  minConnections?: number;
  /** Specific node IDs for subgraph */
  subgraphNodeIds?: string[];
  /** Node click callback */
  onNodeClick?: (node: NodeData | null) => void;
  /** Highlight specific nodes */
  highlightNodeIds?: string[];
}

/**
 * Props for the Controls subcomponent
 */
export interface ControlsProps {
  /** Additional CSS class name */
  className?: string;
  /** Custom render for toolbar content */
  renderCustom?: React.ReactNode;
}

/**
 * Props for the NodeInfoPanel subcomponent
 */
export interface NodeInfoPanelProps {
  /** Currently selected node data */
  node: NodeData | null;
  /** Close callback */
  onClose?: () => void;
  /** Panel position: 'right' | 'left' | 'float' */
  position?: 'right' | 'left' | 'float';
  /** Additional CSS class name */
  className?: string;
}

/**
 * Props for the Stats subcomponent (optional)
 */
export interface StatsProps {
  /** Node count */
  nodeCount?: number;
  /** Edge count */
  edgeCount?: number;
  /** Loading state */
  loading?: boolean;
}

/**
 * Props for the Legend subcomponent (optional)
 */
export interface LegendProps {
  /** Include communities in legend */
  includeCommunities?: boolean;
  /** Custom legend items */
  customItems?: Array<{ color: string; label: string; size?: string }>;
}

// ========================================
// Legacy Props (Backward Compatibility)
// ========================================

/**
 * Legacy props for backward compatibility
 */
export interface LegacyCytoscapeGraphProps {
  projectId?: string;
  tenantId?: string;
  includeCommunities?: boolean;
  minConnections?: number;
  onNodeClick?: (node: NodeData | null) => void;
  highlightNodeIds?: string[];
  subgraphNodeIds?: string[];
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
