import type { ReactNode } from 'react';

import { runsInElectronShell } from './features/auth/loginRuntimeModel';
import type { AgentTaskSignal } from './features/chat/agentTaskSignalModel';
import {
  DEVICE_APPROVAL_ROUTE_ID,
  INVITATION_ACCEPTANCE_ROUTE_ID,
} from './features/navigation/desktopProductionRouteRegistry';
import type { SessionCanvasTabId } from './features/session/sessionCanvasModel';
import { unavailableWorkspaceAuthority } from './utils/format';
import type { AgentConversation, AuthState, DesktopRuntimeConfig, RuntimeDataset } from './types';

export type CommandPaletteItem = {
  id: string;
  kind: 'route' | 'settings' | 'action';
  groupId: string;
  groupLabel: string;
  routeId?: string;
  label: string;
  description: string;
  icon: ReactNode;
  shortcut?: string;
  disabled?: boolean;
  disabledReason?: string;
  searchText: string;
  onSelect: () => void;
};

export type SidebarRunItem = {
  id: string;
  label: string;
  status: string;
  meta: string;
  time: string;
  sortTime: number;
  projectId: string;
  workspaceId?: string;
  conversation?: AgentConversation;
};
export type ReviewTab =
  | SessionCanvasTabId
  | 'pull'
  | 'background'
  | 'agents'
  | 'graph'
  | 'insights'
  | 'context'
  | 'runtime';
export type WorkspaceArtifactKind = 'Files' | 'Patches' | 'Reports' | 'Logs' | 'Events';
export type WorkspaceArtifact = {
  id: string;
  name: string;
  path: string;
  kind: WorkspaceArtifactKind;
  source: string;
  status: string;
  time: string;
  sortTime: number;
  size: string;
  diff: string;
  preview: string;
  raw: unknown;
  searchableText: string;
};
export type ReviewDecisionArtifact = {
  id: string;
  name: string;
  path: string;
  meta: string;
  diff: string;
};
export type ReviewDecisionSummary = {
  title: string;
  summary: string;
  reasoning: string;
  risk: 'Low' | 'Medium' | 'High' | 'Unassessed';
  changeValue: string;
  filesChanged: number;
  artifacts: ReviewDecisionArtifact[];
  checks: Array<{ label: string; value: string }>;
  canAct: boolean;
};
export type AgentConversationSession = {
  scopeKey: string;
  conversation: AgentConversation;
};

export function agentConversationSelectionIdentity(session: AgentConversationSession | null) {
  return session ? { scopeKey: session.scopeKey, conversationId: session.conversation.id } : null;
}

export type AgentTaskSignalPatch = Partial<Omit<AgentTaskSignal, 'id'>> & {
  id: string;
};

export function detectNativeDesktopShell(): boolean {
  if (typeof window === 'undefined') return false;
  return Boolean(
    runsInElectronShell() || document.documentElement.hasAttribute('data-desktop-window'),
  );
}

export function localRuntimeSidecarConfig(config: DesktopRuntimeConfig) {
  return {
    workspace_root: config.workspaceRoot,
  };
}

export function isEditableEventTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return Boolean(target.closest('input, textarea, select, [contenteditable="true"]'));
}

export function agentConversationScopeKey(config: DesktopRuntimeConfig): string {
  return agentConversationScopeKeyFor(config.projectId, config.workspaceId);
}

export function agentConversationScopeKeyFor(projectId: string, workspaceId: string): string {
  return `${projectId.trim()}::${workspaceId.trim()}`;
}

export type WorkspaceSsoFlowErrorCode = 'credential_store' | 'invalid_url' | 'expired';

export class WorkspaceSsoFlowError extends Error {
  readonly code: WorkspaceSsoFlowErrorCode;

  constructor(code: WorkspaceSsoFlowErrorCode) {
    super(code);
    this.name = 'WorkspaceSsoFlowError';
    this.code = code;
  }
}

export const SIDEBAR_WIDTH_STORAGE_KEY = 'agistack.desktop.sidebarWidth';
export const SIDEBAR_WIDTH_CONSTRAINTS = {
  min: 180,
  max: 420,
  default: 220,
} as const;
export const AUTHENTICATION_PASSTHROUGH_ROUTE_IDS: ReadonlySet<string> = new Set([
  DEVICE_APPROVAL_ROUTE_ID,
  INVITATION_ACCEPTANCE_ROUTE_ID,
]);

export const emptyDataset: RuntimeDataset = {
  workspaces: [],
  workspacesByProject: {},
  conversationsByWorkspace: {},
  nodeState: { projects: {}, workspaces: {} },
  messages: [],
  tasks: [],
  plan: null,
  workspaceMembers: unavailableWorkspaceAuthority(),
  workspaceAgents: unavailableWorkspaceAuthority(),
  sandbox: null,
  myWork: [],
  myWorkError: null,
};

export const emptyAuthState: AuthState = {
  status: 'signed_out',
  credentialKind: null,
  session: null,
  context: null,
  user: null,
  tenants: [],
  projects: [],
  mustChangePassword: false,
  error: null,
};
