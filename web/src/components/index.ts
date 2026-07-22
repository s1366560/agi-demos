/**
 * Components Index - DEPRECATED for direct imports
 *
 * PERFORMANCE NOTE: For optimal tree-shaking, import from sub-barrels instead:
 *
 *   GOOD: import { ErrorBoundary } from '@/components/common'
 *   GOOD: import { MessageArea } from '@/components/agent'
 *   BAD:  import { ErrorBoundary } from '@/components'
 *
 * This file exists primarily for TypeScript IDE support and documentation.
 * Direct imports from here may cause larger bundle sizes due to tree-shaking limitations.
 *
 * Available sub-barrels:
 *   - @/components/common - ErrorBoundary, SkeletonLoader
 *   - @/components/agent - MessageArea, InputBar
 *   - @/components/shared - Modal components, UI components
 *   - @/components/graph - CytoscapeGraph, EntityCard
 *   - @/components/agent/layout - LayoutModeSelector
 *   - @/components/agent/chat - MarkdownContent, ChatSearch
 *   - @/components/agent/execution - ActivityTimeline, ToolCallVisualization
 *   - @/components/agent/sandbox - SandboxTerminal, SandboxControlPanel
 *   - @/components/agent/patterns - PatternList, PatternInspector
 */

// Re-exports for IDE support - prefer sub-barrel imports in production code

// Common components (ErrorBoundary, SkeletonLoader)
export { ErrorBoundary, SkeletonLoader, type SkeletonLoaderProps } from './common';

// Agent components (modern agent chat UI)
export { MessageArea, MessageBubble, InputBar, RightPanel, SandboxSection } from './agent';

// Shared components (modals, UI components)
export { DeleteConfirmationModal, LanguageSwitcher, ThemeToggle } from './shared';

// Graph components (knowledge graph visualization)
export {
  CytoscapeGraph,
  EntityCard,
  getEntityTypeColor,
  type Entity,
  type EntityCardProps,
} from './graph';
