/**
 * CytoscapeGraph Component - Legacy Entry Point
 *
 * This file re-exports the new refactored CytoscapeGraph component
 * to maintain backward compatibility with existing imports.
 *
 * The actual implementation is now in the CytoscapeGraph/ directory
 * following the composite component pattern.
 *
 * @deprecated Prefer importing from '@/components/graph/CytoscapeGraph' directly
 */

export { CytoscapeGraph, CytoscapeGraph as default } from './CytoscapeGraph/CytoscapeGraph';
export type {
  GraphConfig,
  NodeData,
  ViewportProps,
  NodeInfoPanelProps,
  CytoscapeGraphProps,
  LegacyCytoscapeGraphProps,
} from './CytoscapeGraph/types';
