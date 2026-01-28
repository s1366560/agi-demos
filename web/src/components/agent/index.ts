/**
 * Agent components index
 *
 * Exports all agent-related UI components.
 */

// V3 Components (modern, Tailwind-based) - exported as defaults
export { ChatLayout } from './ChatLayoutV3';
export { ConversationSidebar } from './ConversationSidebarV3';
export { MessageList } from './MessageListV3';
export { MessageBubble } from './MessageBubbleV3';
export { InputArea } from './InputAreaV3';
export { ThinkingChain } from './ThinkingChainV3';
export { ToolCard } from './ToolCardV3';
export { PlanViewer } from './PlanViewerV3';
export { RightPanel } from './RightPanelV3';
export {
  ExecutionDetailsPanel,
  type ExecutionDetailsPanelProps,
  type ViewType,
} from './ExecutionDetailsPanel';

// Legacy Ant Design components (to be migrated) - exported with Legacy suffix
export { MessageBubble as MessageBubbleLegacy } from './MessageBubble';
export { MessageInput } from './MessageInput';
export { ConversationSidebar as ConversationSidebarLegacy } from './ConversationSidebar';
export { ProjectSelector } from './ProjectSelector';
export { WorkPlanCard } from './WorkPlanCard';
export { ToolExecutionCard } from './ToolExecutionCard';
export { TenantAgentConfigEditor } from './TenantAgentConfigEditor';
export { TenantAgentConfigView } from './TenantAgentConfigView';
export { ReportViewer } from './ReportViewer';
export { TableView } from './TableView';
export { ClarificationDialog } from './ClarificationDialog';
export { DecisionModal } from './DecisionModal';
export { DoomLoopInterventionModal } from './DoomLoopInterventionModal';
export { ExecutionStatsCard } from './ExecutionStatsCard';
export { ExecutionTimelineChart } from './ExecutionTimelineChart';
export { AgentProgressBar } from './AgentProgressBar';
export { PlanEditor } from './PlanEditor';
export { PlanModeIndicator } from './PlanModeIndicator';
export { ThoughtBubble } from './ThoughtBubble';
export { CodeExecutorResultCard } from './CodeExecutorResultCard';
export { FileDownloadButton } from './FileDownloadButton';
export { WebScrapeResultCard } from './WebScrapeResultCard';
export { WebSearchResultCard } from './WebSearchResultCard';
export { SkillExecutionCard } from './SkillExecutionCard';

// New Tailwind components
export { WorkspaceSidebar, TopNavigation, ChatHistorySidebar } from './layout';
export { IdleState, FloatingInputBar } from './chat';
export {
  WorkPlanProgress,
  ToolExecutionLive,
  ReasoningLog,
  FinalReport,
  FollowUpPills,
} from './execution';
export { PatternStats, PatternList, PatternInspector } from './patterns';
export { MaterialIcon } from './shared';

// Types
export type { StarterTile } from './chat';
export type { StepStatus, WorkPlanStep } from './execution';
export type { SidebarConversationStatus, Conversation } from './layout';
export type { PatternStatus, WorkflowPattern } from './patterns';
