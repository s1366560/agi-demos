/**
 * Agent components index
 *
 * Exports all agent-related UI components.
 */

// Primary Agent Chat Components (Modern Design)
export { MessageArea } from '@business/agent/ui/web/transcript/MessageArea';
export { MessageBubble } from '@business/agent/ui/web/transcript/MessageBubble';
export { InputBar } from './InputBar';
export { RightPanel } from './RightPanel';
export { SandboxSection } from '@business/environments/ui/web/components/SandboxSection';

// ProjectReActAgent Lifecycle Status Bar
export { ProjectAgentStatusBar } from './ProjectAgentStatusBar';

// Resizer component for draggable panels
export { Resizer } from '../layout/Resizer';

// Utility Components
export { TenantAgentConfigEditor } from '@business/agent/ui/web/configuration/TenantAgentConfigEditor';
export { TenantAgentConfigView } from '@business/agent/ui/web/configuration/TenantAgentConfigView';
export { InlineHITLCard } from './InlineHITLCard';
export { AgentProgressBar } from './AgentProgressBar';

// Timeline Components
export { PatternStats, PatternList, PatternInspector } from './patterns';

// Types
export type { PatternStatus, WorkflowPattern } from './patterns';
