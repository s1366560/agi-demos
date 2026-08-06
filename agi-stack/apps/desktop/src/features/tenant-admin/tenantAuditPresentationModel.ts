import type { TenantAdminPresentationInput } from './tenantAdminController';
import type { TenantAdminScope } from './tenantAdminHttp';
import type {
  TenantAuditData,
  TenantAuditEntry,
  TenantAuditRuntimeSummary,
} from './tenantAuditClient';

export type TenantAuditViewModel = Readonly<{
  state: TenantAdminPresentationInput<TenantAdminScope, TenantAuditData>['state'];
  scope: TenantAdminScope;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: string | null;
  allowedActions: readonly string[];
  entries: readonly TenantAuditEntry[];
  total: number;
  limit: number;
  offset: number;
  runtimeSummary: TenantAuditRuntimeSummary | null;
  query: TenantAuditData['query'];
}>;

const EMPTY_QUERY = Object.freeze({ limit: 20, offset: 0 });

export function buildTenantAuditPresentation(
  input: TenantAdminPresentationInput<TenantAdminScope, TenantAuditData>,
): TenantAuditViewModel {
  return Object.freeze({
    state: input.state,
    scope: input.scope,
    reasonCode: input.reasonCode,
    retryVisible: input.retryVisible,
    busyAction: input.busyAction,
    allowedActions: input.snapshot?.allowedActions ?? Object.freeze([]),
    entries: input.snapshot?.data.entries ?? Object.freeze([]),
    total: input.snapshot?.data.total ?? 0,
    limit: input.snapshot?.data.limit ?? 20,
    offset: input.snapshot?.data.offset ?? 0,
    runtimeSummary: input.snapshot?.data.runtimeSummary ?? null,
    query: input.snapshot?.data.query ?? EMPTY_QUERY,
  });
}
