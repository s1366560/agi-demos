export type ProjectSupportAuthority = 'cloud' | 'local';
export type ProjectSupportAvailability =
  | 'available'
  | 'degraded'
  | 'unavailable'
  | 'not_applicable';
export type ProjectSupportPriority = 'low' | 'medium' | 'high' | 'urgent';
export type ProjectSupportStatus =
  | 'open'
  | 'in_progress'
  | 'resolved'
  | 'closed';

export type ProjectSupportScope = Readonly<{
  authority: ProjectSupportAuthority;
  tenantId: string;
  projectId: string;
}>;

export type ProjectSupportTicket = Readonly<{
  id: string;
  tenantId: string;
  subject: string;
  message: string;
  priority: ProjectSupportPriority;
  status: ProjectSupportStatus;
  createdAt: string;
  updatedAt: string;
  resolvedAt: string | null;
  allowedActions: readonly string[];
}>;

export type ProjectSupportListQuery = Readonly<{
  limit?: number;
  offset?: number;
}>;

export type ProjectSupportListSnapshot = Readonly<{
  scope: ProjectSupportScope;
  authority: ProjectSupportAuthority;
  availability: ProjectSupportAvailability;
  reasonCode: string | null;
  serviceVersion: string | null;
  contractVersion: string | null;
  allowedActions: readonly string[];
  authorityRevision: number | null;
  tickets: readonly ProjectSupportTicket[];
  total: number;
  limit: number;
  offset: number;
  hasMore: boolean;
}>;

export type ProjectSupportCreateInput = Readonly<{
  subject: string;
  message: string;
  priority: ProjectSupportPriority;
}>;

export type ProjectSupportCloseResult = Readonly<{
  id: string;
  status: 'closed';
  resolvedAt: string;
}>;

export type ProjectSupportRequestOptions = Readonly<{
  signal?: AbortSignal;
}>;

export type ProjectSupportClient = Readonly<{
  list: (
    scope: ProjectSupportScope,
    query?: ProjectSupportListQuery,
    options?: ProjectSupportRequestOptions,
  ) => Promise<ProjectSupportListSnapshot>;
  create: (
    scope: ProjectSupportScope,
    input: ProjectSupportCreateInput,
    options?: ProjectSupportRequestOptions,
  ) => Promise<ProjectSupportTicket>;
  close: (
    scope: ProjectSupportScope,
    ticketId: string,
    options?: ProjectSupportRequestOptions,
  ) => Promise<ProjectSupportCloseResult>;
}>;
