import type { TenantAdminRole } from './tenantAdminHttp';
import type {
  TenantManagementPresentationInput,
  TenantManagementViewState,
} from './tenantManagementController';
import type { TenantManagementScope } from './tenantManagementHttp';
import type {
  TenantGenePolicy,
  TenantOrganizationSettingsData,
  TenantRegistry,
  TenantSmtpConfig,
} from './tenantOrganizationSettingsClient';
import type { TenantSettingsTenant } from './tenantSettingsClient';

export type TenantOrganizationSettingsViewModel = Readonly<{
  state: TenantManagementViewState;
  scope: TenantManagementScope;
  reasonCode: string | null;
  retryVisible: boolean;
  busyAction: string | null;
  allowedActions: readonly string[];
  membershipRole: TenantAdminRole | null;
  tenant: TenantSettingsTenant | null;
  stats: Readonly<Record<string, unknown>>;
  registries: readonly TenantRegistry[];
  smtp: TenantSmtpConfig | null;
  genePolicies: readonly TenantGenePolicy[];
}>;

export function buildTenantOrganizationSettingsPresentation(
  input: TenantManagementPresentationInput<
    TenantManagementScope,
    TenantOrganizationSettingsData
  >,
): TenantOrganizationSettingsViewModel {
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
    registries: input.snapshot?.data.registries ?? Object.freeze([]),
    smtp: input.snapshot?.data.smtp ?? null,
    genePolicies: input.snapshot?.data.genePolicies ?? Object.freeze([]),
  });
}
