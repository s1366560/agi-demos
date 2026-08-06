export type ProjectWorkspacesAuthority = 'cloud' | 'local';

export type ProjectWorkspacesScope = Readonly<{
  authority: ProjectWorkspacesAuthority;
  tenantId: string;
  projectId: string;
}>;

export type ProjectWorkspaceRecord = Readonly<{
  id: string;
  tenantId: string;
  projectId: string;
  name: string;
  description: string;
  archived: boolean;
  createdAt: string | null;
  updatedAt: string | null;
}>;

export type ProjectWorkspaceMember = Readonly<{
  id: string;
  workspaceId: string;
  userId: string;
  email: string | null;
  role: 'owner' | 'editor' | 'viewer';
}>;

export type ProjectWorkspaceAgentBinding = Readonly<{
  id: string;
  workspaceId: string;
  agentId: string;
  displayName: string | null;
  active: boolean;
  status: string | null;
}>;

export type ProjectWorkspaceCreateInput = Readonly<{
  name: string;
  description: string;
}>;

export type ProjectWorkspaceUpdateInput = Readonly<{
  name: string;
  description: string;
  archived: boolean;
}>;

export type ProjectWorkspaceMemberInput = Readonly<{
  userId: string;
  role: ProjectWorkspaceMember['role'];
}>;

export type ProjectWorkspaceAgentInput = Readonly<{
  agentId: string;
  displayName?: string;
  description?: string;
}>;

export type ProjectWorkspacesRequestOptions = Readonly<{
  signal?: AbortSignal;
}>;

export type ProjectWorkspacesSnapshot = Readonly<{
  scope: ProjectWorkspacesScope;
  authority: ProjectWorkspacesAuthority;
  availability: 'available' | 'degraded';
  reasonCode: string | null;
  serviceVersion: string;
  contractVersion: '1.0.0';
  authorityRevision: number | null;
  allowedActions: readonly string[];
  workspaces: readonly ProjectWorkspaceRecord[];
}>;

export interface ProjectWorkspacesClient {
  list(
    scope: ProjectWorkspacesScope,
    options?: ProjectWorkspacesRequestOptions,
  ): Promise<ProjectWorkspacesSnapshot>;
  create(
    scope: ProjectWorkspacesScope,
    input: ProjectWorkspaceCreateInput,
    options?: ProjectWorkspacesRequestOptions,
  ): Promise<ProjectWorkspaceRecord>;
  update(
    scope: ProjectWorkspacesScope,
    workspaceId: string,
    input: ProjectWorkspaceUpdateInput,
    options?: ProjectWorkspacesRequestOptions,
  ): Promise<ProjectWorkspaceRecord>;
  listMembers(
    scope: ProjectWorkspacesScope,
    workspaceId: string,
    options?: ProjectWorkspacesRequestOptions,
  ): Promise<readonly ProjectWorkspaceMember[]>;
  addMember(
    scope: ProjectWorkspacesScope,
    workspaceId: string,
    input: ProjectWorkspaceMemberInput,
    options?: ProjectWorkspacesRequestOptions,
  ): Promise<ProjectWorkspaceMember>;
  updateMemberRole(
    scope: ProjectWorkspacesScope,
    workspaceId: string,
    userId: string,
    role: ProjectWorkspaceMember['role'],
    options?: ProjectWorkspacesRequestOptions,
  ): Promise<ProjectWorkspaceMember>;
  removeMember(
    scope: ProjectWorkspacesScope,
    workspaceId: string,
    userId: string,
    options?: ProjectWorkspacesRequestOptions,
  ): Promise<void>;
  listAgents(
    scope: ProjectWorkspacesScope,
    workspaceId: string,
    options?: ProjectWorkspacesRequestOptions,
  ): Promise<readonly ProjectWorkspaceAgentBinding[]>;
  bindAgent(
    scope: ProjectWorkspacesScope,
    workspaceId: string,
    input: ProjectWorkspaceAgentInput,
    options?: ProjectWorkspacesRequestOptions,
  ): Promise<ProjectWorkspaceAgentBinding>;
  unbindAgent(
    scope: ProjectWorkspacesScope,
    workspaceId: string,
    bindingId: string,
    options?: ProjectWorkspacesRequestOptions,
  ): Promise<void>;
}
