import type { TenantAdminRole } from './tenantAdminHttp';
import type {
  TenantManagementPresentationInput,
  TenantManagementViewState,
} from './tenantManagementController';
import type { TenantManagementScope } from './tenantManagementHttp';
import type { TenantWebhook, TenantWebhooksData } from './tenantWebhooksClient';

export type TenantWebhooksViewModel = Readonly<{
  state: TenantManagementViewState;
  scope: TenantManagementScope;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: string | null;
  allowedActions: readonly string[];
  membershipRole: TenantAdminRole | null;
  webhooks: readonly TenantWebhook[];
  eventTypes: readonly string[];
}>;

export function buildTenantWebhooksPresentation(
  input: TenantManagementPresentationInput<TenantManagementScope, TenantWebhooksData>,
): TenantWebhooksViewModel {
  return Object.freeze({
    state: input.state,
    scope: input.scope,
    reasonCode: input.reasonCode,
    retryVisible: input.retryVisible,
    busyAction: input.busyAction,
    allowedActions: input.snapshot?.allowedActions ?? Object.freeze([]),
    membershipRole: input.snapshot?.data.membershipRole ?? null,
    webhooks: input.snapshot?.data.webhooks ?? Object.freeze([]),
    eventTypes: input.snapshot?.data.eventTypes ?? Object.freeze([]),
  });
}
