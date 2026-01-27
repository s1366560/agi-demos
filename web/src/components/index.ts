/**
 * Root Components Barrel Export
 *
 * TDD Phase 1.2: Barrel Exports
 *
 * This file provides a centralized export point for all components.
 * Use this to import components with cleaner paths:
 *
 *   import { ErrorBoundary, WorkPlanCard } from '@/components'
 *
 * For more specific imports, use the sub-barrels:
 *   import { ChatLayout } from '@/components/agentV3'
 *   import { WorkspaceSidebar } from '@/components/agent/layout'
 */

// Common components (ErrorBoundary, SkeletonLoader, EmptyState)
export {
    ErrorBoundary,
    SkeletonLoader,
    EmptyState,
    type EmptyStateProps,
    type SkeletonLoaderProps,
} from './common'

// AgentV3 components (modern agent chat UI)
export {
    ChatLayout,
    ConversationSidebar,
    MessageList,
    MessageBubble,
    InputArea,
    ThinkingChain,
    ToolCard,
    PlanViewer,
    ExecutionDetailsPanel,
    type ExecutionDetailsPanelProps,
    type ViewType,
} from './agentV3'

// Note: For specific agent sub-categories, import directly from sub-barrels:
// - Layout: import { WorkspaceSidebar } from '@/components/agent/layout'
// - Chat: import { IdleState } from '@/components/agent/chat'
// - Execution: import { WorkPlanProgress } from '@/components/agent/execution'
// - Patterns: import { PatternList } from '@/components/agent/patterns'
// - Sandbox: import { SandboxTerminal } from '@/components/agent/sandbox'
