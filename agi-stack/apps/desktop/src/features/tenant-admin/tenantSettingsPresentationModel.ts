import type { TenantAdminRole } from './tenantAdminHttp';
import type {
  TenantManagementPresentationInput,
  TenantManagementViewState,
} from './tenantManagementController';
import type { TenantManagementScope } from './tenantManagementHttp';
import type { TenantSettingsData, TenantSettingsTenant } from './tenantSettingsClient';

export type TenantSettingsViewModel = Readonly<{
  state: TenantManagementViewState;
  scope: TenantManagementScope;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: string | null;
  allowedActions: readonly string[];
  membershipRole: TenantAdminRole | null;
  tenant: TenantSettingsTenant | null;
  stats: Readonly<Record<string, unknown>>;
}>;

export function buildTenantSettingsPresentation(
  input: TenantManagementPresentationInput<TenantManagementScope, TenantSettingsData>,
): TenantSettingsViewModel {
  return Object.freeze({
    state: input.state,
    scope: input.scope,
    reasonCode: input.reasonCode,
    retryVisible: input.retryVisible,
    busyAction: input.busyAction,
    allowedActions: input.snapshot?.allowedActions ?? Object.freeze([]),
    membershipRole: input.snapshot?.data.membershipRole ?? null,
    tenant: input.snapshot?.data.tenant ?? null,
    stats: input.snapshot?.data.stats ?? Object.freeze({}),
  });
}
