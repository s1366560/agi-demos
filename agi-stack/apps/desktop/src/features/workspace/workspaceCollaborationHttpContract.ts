export type WorkspaceHttpScope = {
  tenantId: string;
  projectId: string;
  workspaceId: string;
};

export class WorkspaceCollaborationContractError extends Error {
  readonly reason_code: string;
  readonly status: number | null;
  readonly payload: unknown;

  constructor(reasonCode: string, status: number | null = null, payload: unknown = null) {
    super(reasonCode);
    this.name = 'WorkspaceCollaborationContractError';
    this.reason_code = reasonCode;
    this.status = status;
    this.payload = payload;
  }
}

export function workspaceContractError(
  reasonCode: string,
  status: number | null = null,
  payload: unknown = null,
): WorkspaceCollaborationContractError {
  return new WorkspaceCollaborationContractError(reasonCode, status, payload);
}

export function requireWorkspaceRecord(
  input: unknown,
  reasonCode: string,
): Record<string, unknown> {
  if (!isWorkspaceRecord(input)) throw workspaceContractError(reasonCode);
  return input;
}

export function isWorkspaceRecord(input: unknown): input is Record<string, unknown> {
  return typeof input === 'object' && input !== null && !Array.isArray(input);
}

export function scopedWorkspacePath(scope: WorkspaceHttpScope): string {
  return (
    `/api/v1/tenants/${encodeURIComponent(scope.tenantId)}/projects/` +
    `${encodeURIComponent(scope.projectId)}/workspaces/${encodeURIComponent(scope.workspaceId)}`
  );
}

export function workspaceRootPath(scope: WorkspaceHttpScope): string {
  return `/api/v1/workspaces/${encodeURIComponent(scope.workspaceId)}`;
}
