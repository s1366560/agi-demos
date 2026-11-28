import type { ReactNode } from 'react';
import { DesktopSidebarFrame } from './DesktopSidebarFrame';
import type { LocalConversationStatusSummary } from '@business/workspace/ui/desktop/project/projectOverviewLocalClient';
import type {
  AgentConversation,
  CurrentUser,
  RuntimeNodeLoadState,
  WorkspaceSummary,
} from '../../types';
import { WorkspaceDock } from '../workspace/WorkspaceDock';
import type { ExecutionTargetFilter } from '../session/ExecutionTargetBadge';
import type { WorkspaceTreeSelectionMode } from '@business/workspace/ui/desktop/workspace/workspaceTreeModel';

type DesktopSidebarSection = 'home' | 'my-work' | 'activity';

type DesktopSidebarProps = {
  activeSection: DesktopSidebarSection | null;
  mode?: 'work' | 'code';
  taskCount: number;
  activityUnreadCount: number;
  conversationStatusSummary?: LocalConversationStatusSummary | null;
  tenantName: string;
  projectName: string;
  user: CurrentUser | null;
  workspaces: WorkspaceSummary[];
  conversationsByWorkspace: Record<string, AgentConversation[]>;
  nodeState: RuntimeNodeLoadState;
  currentProjectId: string;
  currentWorkspaceId: string;
  currentConversationId: string | null;
  workspaceTreeSelectionMode: WorkspaceTreeSelectionMode;
  expandedWorkspaceIds: Set<string>;
  newTaskDisabledReason: string | null;
  onModeChange?: (mode: 'work' | 'code') => void;
  onNavigate: (section: DesktopSidebarSection) => void;
  onOpenSearch?: () => void;
  onOpenFeatureDirectory?: (trigger: HTMLButtonElement) => void;
  onToggleWorkspace: (workspaceId: string) => void;
  onRetryProject: () => void;
  onRetryWorkspace: (workspaceId: string) => void;
  onSelectWorkspace: (projectId: string, workspaceId: string) => void;
  onSelectConversation: (
    projectId: string,
    workspaceId: string,
    conversation: AgentConversation,
  ) => void;
  onRenameConversation?: (
    projectId: string,
    workspaceId: string,
    conversation: AgentConversation,
    title: string,
  ) => Promise<void>;
  onDeleteConversation?: (
    projectId: string,
    workspaceId: string,
    conversation: AgentConversation,
  ) => Promise<void>;
  workspaceCreateDisabledReason?: string | null;
  onCreateWorkspace?: () => void;
  onNewTask: () => void;
  executionTarget?: ExecutionTargetFilter;
  onExecutionTargetChange?: (value: ExecutionTargetFilter) => void;
  onOpenAccountSettings: () => void;
  onSwitchWorkspace: () => void;
  onSignOut: () => void;
  resizeHandle?: ReactNode;
};

export function DesktopSidebar({
  tenantName,
  projectName,
  user,
  workspaces,
  conversationsByWorkspace,
  nodeState,
  currentProjectId,
  currentWorkspaceId,
  currentConversationId,
  workspaceTreeSelectionMode,
  expandedWorkspaceIds,
  newTaskDisabledReason,
  onNavigate,
  onOpenSearch,
  onOpenFeatureDirectory,
  onToggleWorkspace,
  onRetryProject,
  onRetryWorkspace,
  onSelectWorkspace,
  onSelectConversation,
  onRenameConversation,
  onDeleteConversation,
  workspaceCreateDisabledReason,
  onCreateWorkspace,
  onNewTask,
  executionTarget,
  onExecutionTargetChange,
  onOpenAccountSettings,
  onSwitchWorkspace,
  onSignOut,
  resizeHandle,
}: DesktopSidebarProps) {
  return (
    <DesktopSidebarFrame
      tenantName={tenantName}
      projectName={projectName}
      user={user}
      newTaskDisabledReason={newTaskDisabledReason}
      onNavigate={onNavigate}
      onOpenSearch={onOpenSearch}
      onOpenFeatureDirectory={onOpenFeatureDirectory}
      workspaceCreateDisabledReason={workspaceCreateDisabledReason}
      onCreateWorkspace={onCreateWorkspace}
      onNewTask={onNewTask}
      onOpenAccountSettings={onOpenAccountSettings}
      onSwitchWorkspace={onSwitchWorkspace}
      onSignOut={onSignOut}
      resizeHandle={resizeHandle}
      workspaceDock={
        <WorkspaceDock
          workspaces={workspaces}
          conversationsByWorkspace={conversationsByWorkspace}
          nodeState={nodeState}
          currentProjectId={currentProjectId}
          currentWorkspaceId={currentWorkspaceId}
          currentConversationId={currentConversationId}
          selectionMode={workspaceTreeSelectionMode}
          expandedWorkspaceIds={expandedWorkspaceIds}
          onToggleWorkspace={onToggleWorkspace}
          onRetryProject={onRetryProject}
          onRetryWorkspace={onRetryWorkspace}
          onSelectWorkspace={onSelectWorkspace}
          onSelectConversation={onSelectConversation}
          onRenameConversation={onRenameConversation}
          onDeleteConversation={onDeleteConversation}
          onCreateWorkspace={workspaceCreateDisabledReason ? undefined : onCreateWorkspace}
          executionTarget={executionTarget}
          onExecutionTargetChange={onExecutionTargetChange}
        />
      }
    />
  );
}
