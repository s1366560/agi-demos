/**
 * Components Index - DEPRECATED for direct imports
 *
 * PERFORMANCE NOTE: For optimal tree-shaking, import from sub-barrels instead:
 *
 *   GOOD: import { ErrorBoundary } from '@/components/common'
 *   GOOD: import { ConversationSidebar } from '@/components/agent'
 *   BAD:  import { ErrorBoundary } from '@/components'
 *
 * This file exists primarily for TypeScript IDE support and documentation.
 * Direct imports from here may cause larger bundle sizes due to tree-shaking limitations.
 *
 * Available sub-barrels:
 *   - @/components/common - ErrorBoundary, SkeletonLoader, EmptyState
 *   - @/components/agent - ConversationSidebar, MessageArea
 *   - @/components/shared - Modal components, UI components
 *   - @/components/graph - GraphVisualization, EntityCard
 *   - @/components/agent/layout - WorkspaceSidebar, ResizablePanels
 *   - @/components/agent/chat - MessageBubble, InputBar, IdleState
 *   - @/components/agent/execution - WorkPlanProgress, ToolExecutionCard
 *   - @/components/agent/sandbox - SandboxTerminal, SandboxPanel
 *   - @/components/agent/patterns - PatternList, ThinkingChain
 */

// Re-exports for IDE support - prefer sub-barrel imports in production code

// Common components (ErrorBoundary, SkeletonLoader, EmptyState)
export {
  ErrorBoundary,
  SkeletonLoader,
  EmptyState,
  type EmptyStateProps,
  type SkeletonLoaderProps,
} from './common';

// Agent components (modern agent chat UI)
export {
  ConversationSidebar,
  MessageArea,
  MessageBubble,
  InputBar,
  RightPanel,
  PlanModeBanner,
  SandboxSection,
} from './agent';

// Shared components (modals, UI components)
export {
  DeleteConfirmationModal,
  LanguageSwitcher,
  NotificationPanel,
  ThemeToggle,
  WorkspaceSwitcher,
} from './shared';

// Graph components (knowledge graph visualization)
export {
  GraphVisualization,
  CytoscapeGraph,
  EntityCard,
  getEntityTypeColor,
  type Entity,
  type EntityCardProps,
} from './graph';
