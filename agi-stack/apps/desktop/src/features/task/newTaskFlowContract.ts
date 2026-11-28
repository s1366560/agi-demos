import type {
  AgentConversation,
  AgentInputFileMetadata,
  AgentPlanTask,
  DesktopRuntimeConfig,
  WorkspaceSummary,
} from '../../types';
import type { NewTaskDefinition } from './newTaskPlanModel';

export type NewTaskSession = {
  workspace: WorkspaceSummary;
  conversation: AgentConversation;
  config: DesktopRuntimeConfig;
};

export type NewTaskAgentTurnInput = {
  displayContent?: string;
  config: DesktopRuntimeConfig;
  conversationId: string;
  projectId: string;
  message: string;
  messageId: string;
  agentId?: string;
  forcedSkillName?: string;
  subAgentId?: string;
  mentions?: string[];
  fileMetadata?: AgentInputFileMetadata[];
  appModelContext?: Record<string, unknown>;
};

export type NewTaskResumeDraft = {
  session: NewTaskSession;
  definition: NewTaskDefinition;
  tasks: AgentPlanTask[];
};
