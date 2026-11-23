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

export type ProjectWorkspaceCreateInput = Readonly<{
  name: string;
  description: string;
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
}
