export type TenantWorkspacesAuthority = 'cloud' | 'local';

export type TenantWorkspacesScope = Readonly<{
  authority: TenantWorkspacesAuthority;
  tenantId: string;
  projectId: string;
}>;

export type TenantWorkspaceRecord = Readonly<{
  id: string;
  tenantId: string;
  projectId: string;
  name: string;
  description: string;
  status: string;
  archived: boolean;
  createdAt: string | null;
  updatedAt: string | null;
}>;

export type TenantWorkspaceCreateInput = Readonly<{
  name: string;
  description: string;
}>;

export type TenantWorkspacesSnapshot = Readonly<{
  scope: TenantWorkspacesScope;
  authority: TenantWorkspacesAuthority;
  availability: 'available' | 'degraded' | 'unavailable';
  reasonCode: string | null;
  serviceVersion: string;
  contractVersion: string;
  allowedActions: readonly string[];
  authorityRevision: number | null;
  workspaces: readonly TenantWorkspaceRecord[];
}>;

export type TenantWorkspacesRequestOptions = Readonly<{
  signal?: AbortSignal;
}>;

export type TenantWorkspacesClient = Readonly<{
  list: (
    scope: TenantWorkspacesScope,
    options?: TenantWorkspacesRequestOptions,
  ) => Promise<TenantWorkspacesSnapshot>;
  create?: (
    scope: TenantWorkspacesScope,
    input: TenantWorkspaceCreateInput,
    options?: TenantWorkspacesRequestOptions,
  ) => Promise<TenantWorkspaceRecord>;
}>;
