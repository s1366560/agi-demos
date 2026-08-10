import { DesktopApiError } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import type { DesktopCapabilityAvailability } from '../runtime/capabilitySnapshot';
import {
  createTenantAuditClient,
  TENANT_AUDIT_LOCAL_REASON,
  TENANT_AUDIT_ROUTE_ID,
  type TenantAuditClient,
} from './tenantAuditClient';
import {
  createTenantBillingClient,
  TENANT_BILLING_LOCAL_REASON,
  TENANT_BILLING_ROUTE_ID,
  type TenantBillingClient,
} from './tenantBillingClient';
import {
  createTenantGovernanceClient,
  TENANT_GOVERNANCE_LOCAL_REASON,
  TENANT_GOVERNANCE_ROUTE_ID,
  type TenantGovernanceClient,
} from './tenantGovernanceClient';
import {
  createTenantTrustClient,
  TENANT_TRUST_LOCAL_REASON,
  TENANT_TRUST_ROUTE_ID,
  type TenantTrustClient,
} from './tenantTrustClient';

const SERVICE_VERSION = '0.1.0' as const;
const CONTRACT_VERSION = '4.0.0' as const;

export const TENANT_ADMIN_CAPABILITY_IDS = Object.freeze([
  TENANT_GOVERNANCE_ROUTE_ID,
  TENANT_BILLING_ROUTE_ID,
  TENANT_AUDIT_ROUTE_ID,
  TENANT_TRUST_ROUTE_ID,
]);

export type TenantAdminCapabilityId =
  (typeof TENANT_ADMIN_CAPABILITY_IDS)[number];

export type TenantAdminCapabilitySet = Readonly<
  Record<TenantAdminCapabilityId, DesktopCapabilityAvailability>
>;

export type TenantAdminCapabilityClient = Readonly<{
  load(signal?: AbortSignal): Promise<TenantAdminCapabilitySet>;
}>;

export type TenantAdminCapabilityDependencies = Readonly<{
  governance?: Pick<TenantGovernanceClient, 'load'>;
  billing?: Pick<TenantBillingClient, 'load'>;
  audit?: Pick<TenantAuditClient, 'load'>;
  trust?: Pick<TenantTrustClient, 'load'>;
}>;

const REASON_PREFIX = Object.freeze({
  [TENANT_GOVERNANCE_ROUTE_ID]: 'tenant_governance',
  [TENANT_BILLING_ROUTE_ID]: 'tenant_billing',
  [TENANT_AUDIT_ROUTE_ID]: 'tenant_audit',
  [TENANT_TRUST_ROUTE_ID]: 'tenant_trust',
} satisfies Record<TenantAdminCapabilityId, string>);

const LOCAL_REASON = Object.freeze({
  [TENANT_GOVERNANCE_ROUTE_ID]: TENANT_GOVERNANCE_LOCAL_REASON,
  [TENANT_BILLING_ROUTE_ID]: TENANT_BILLING_LOCAL_REASON,
  [TENANT_AUDIT_ROUTE_ID]: TENANT_AUDIT_LOCAL_REASON,
  [TENANT_TRUST_ROUTE_ID]: TENANT_TRUST_LOCAL_REASON,
} satisfies Record<TenantAdminCapabilityId, string>);

const ACTION_CATALOG = Object.freeze({
  [TENANT_GOVERNANCE_ROUTE_ID]: Object.freeze([
    'view',
    'list',
    'invite',
    'inspect-pending-invitation-count',
    'change-role',
    'remove-member',
  ]),
  [TENANT_BILLING_ROUTE_ID]: Object.freeze([
    'view',
    'inspect-usage',
    'list-invoices',
    'upgrade-plan',
  ]),
  [TENANT_AUDIT_ROUTE_ID]: Object.freeze([
    'view',
    'filter',
    'inspect-runtime-hooks',
    'export',
  ]),
  [TENANT_TRUST_ROUTE_ID]: Object.freeze([
    'view',
    'list',
    'create',
    'revoke',
  ]),
} satisfies Record<TenantAdminCapabilityId, readonly string[]>);

export function createTenantAdminCapabilityClient(
  config: DesktopRuntimeConfig,
  dependencies: TenantAdminCapabilityDependencies = {},
): TenantAdminCapabilityClient {
  const runtimeConfig = Object.freeze({ ...config });
  const clients = Object.freeze({
    governance:
      dependencies.governance ?? createTenantGovernanceClient(runtimeConfig),
    billing: dependencies.billing ?? createTenantBillingClient(runtimeConfig),
    audit: dependencies.audit ?? createTenantAuditClient(runtimeConfig),
    trust: dependencies.trust ?? createTenantTrustClient(runtimeConfig),
  });

  return Object.freeze({
    async load(signal?: AbortSignal): Promise<TenantAdminCapabilitySet> {
      const tenantId = identifier(runtimeConfig.tenantId);
      if (!tenantId) {
        return capabilitySet((id) =>
          unavailable(`${REASON_PREFIX[id]}_scope_unavailable`, null, null, 'declared'),
        );
      }
      if (runtimeConfig.mode === 'local') {
        return capabilitySet((id) => notApplicable(LOCAL_REASON[id], tenantId));
      }

      const scope = Object.freeze({ authority: 'cloud' as const, tenantId });
      const workspaceId = identifier(runtimeConfig.workspaceId);
      const [governance, billing, audit, trust] = await Promise.all([
        observeCapability(
          TENANT_GOVERNANCE_ROUTE_ID,
          () => clients.governance.load(scope, { signal }),
          tenantId,
          null,
          signal,
        ),
        observeCapability(
          TENANT_BILLING_ROUTE_ID,
          () => clients.billing.load(scope, { signal }),
          tenantId,
          null,
          signal,
        ),
        observeCapability(
          TENANT_AUDIT_ROUTE_ID,
          () => clients.audit.load(scope, {}, { signal }),
          tenantId,
          null,
          signal,
        ),
        workspaceId
          ? observeCapability(
              TENANT_TRUST_ROUTE_ID,
              () =>
                clients.trust.load(
                  Object.freeze({ ...scope, workspaceId }),
                  { signal },
                ),
              tenantId,
              workspaceId,
              signal,
            )
          : Promise.resolve(
              unavailable(
                'tenant_trust_workspace_scope_unavailable',
                tenantId,
                null,
                'declared',
              ),
            ),
      ]);
      return Object.freeze({
        [TENANT_GOVERNANCE_ROUTE_ID]: governance,
        [TENANT_BILLING_ROUTE_ID]: billing,
        [TENANT_AUDIT_ROUTE_ID]: audit,
        [TENANT_TRUST_ROUTE_ID]: trust,
      });
    },
  });
}

async function observeCapability(
  id: TenantAdminCapabilityId,
  load: () => Promise<unknown>,
  tenantId: string,
  workspaceId: string | null,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  try {
    return normalizeObservation(id, await load(), tenantId, workspaceId);
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error instanceof AuthorityContractError) {
      return unavailable(`${REASON_PREFIX[id]}_authority_contract_invalid`, tenantId, workspaceId);
    }
    if (error instanceof DesktopApiError && error.status === 403) {
      return unavailable(`${REASON_PREFIX[id]}_forbidden`, tenantId, workspaceId);
    }
    if (error instanceof DesktopApiError && error.status === 409) {
      return unavailable(`${REASON_PREFIX[id]}_scope_conflict`, tenantId, workspaceId);
    }
    return unavailable(`${REASON_PREFIX[id]}_authority_unavailable`, tenantId, workspaceId);
  }
}

function normalizeObservation(
  id: TenantAdminCapabilityId,
  input: unknown,
  tenantId: string,
  workspaceId: string | null,
): DesktopCapabilityAvailability {
  if (!isRecord(input) || !isRecord(input.scope)) throw new AuthorityContractError();
  if (
    input.authority !== 'cloud' ||
    input.scope.authority !== 'cloud' ||
    input.scope.tenantId !== tenantId ||
    (workspaceId !== null && input.scope.workspaceId !== workspaceId)
  ) {
    throw new AuthorityContractError();
  }
  if (input.availability !== 'available' && input.availability !== 'degraded') {
    throw new AuthorityContractError();
  }
  const reasonCode = input.reasonCode;
  if (
    (input.availability === 'available' && reasonCode !== null) ||
    (input.availability === 'degraded' && !stableReasonCode(reasonCode))
  ) {
    throw new AuthorityContractError();
  }
  if (
    input.contractVersion !== CONTRACT_VERSION ||
    (input.authorityRevision !== undefined &&
      input.authorityRevision !== null &&
      (!Number.isSafeInteger(input.authorityRevision) ||
        Number(input.authorityRevision) < 0)) ||
    !orderedActionSubset(id, input.allowedActions)
  ) {
    throw new AuthorityContractError();
  }
  const authorityRevision =
    input.authorityRevision === undefined || input.authorityRevision === null
      ? null
      : Number(input.authorityRevision);
  return Object.freeze({
    availability: input.availability,
    reason_code: reasonCode as string | null,
    service_version: SERVICE_VERSION,
    contract_version: CONTRACT_VERSION,
    allowed_actions: Object.freeze([...(input.allowedActions as string[])]),
    scope: capabilityScope(tenantId, workspaceId),
    authority_revision: authorityRevision,
    authority_source: 'cloud_service',
    provenance: 'observed',
  });
}

function capabilitySet(
  build: (id: TenantAdminCapabilityId) => DesktopCapabilityAvailability,
): TenantAdminCapabilitySet {
  return Object.freeze({
    [TENANT_GOVERNANCE_ROUTE_ID]: build(TENANT_GOVERNANCE_ROUTE_ID),
    [TENANT_BILLING_ROUTE_ID]: build(TENANT_BILLING_ROUTE_ID),
    [TENANT_AUDIT_ROUTE_ID]: build(TENANT_AUDIT_ROUTE_ID),
    [TENANT_TRUST_ROUTE_ID]: build(TENANT_TRUST_ROUTE_ID),
  });
}

function notApplicable(
  reasonCode: string,
  tenantId: string,
): DesktopCapabilityAvailability {
  return Object.freeze({
    availability: 'not_applicable',
    reason_code: reasonCode,
    service_version: null,
    contract_version: null,
    allowed_actions: Object.freeze([]),
    scope: capabilityScope(tenantId, null),
    authority_revision: null,
    authority_source: 'renderer',
    provenance: 'declared',
  });
}

function unavailable(
  reasonCode: string,
  tenantId: string | null,
  workspaceId: string | null = null,
  provenance: 'observed' | 'declared' = 'observed',
): DesktopCapabilityAvailability {
  return Object.freeze({
    availability: 'unavailable',
    reason_code: reasonCode,
    service_version: null,
    contract_version: null,
    allowed_actions: Object.freeze([]),
    scope: capabilityScope(tenantId, workspaceId),
    authority_revision: null,
    authority_source: provenance === 'observed' ? 'cloud_service' : 'renderer',
    provenance,
  });
}

function capabilityScope(tenantId: string | null, workspaceId: string | null) {
  return Object.freeze({
    tenant_id: tenantId,
    project_id: null,
    workspace_id: workspaceId,
    instance_id: null,
  });
}

function orderedActionSubset(id: TenantAdminCapabilityId, input: unknown): input is string[] {
  if (!Array.isArray(input) || input.length === 0) return false;
  let previousIndex = -1;
  for (const action of input) {
    if (typeof action !== 'string') return false;
    const index = ACTION_CATALOG[id].indexOf(action);
    if (index <= previousIndex) return false;
    previousIndex = index;
  }
  return true;
}

function identifier(input: unknown): string | null {
  return typeof input === 'string' && input.length > 0 && input === input.trim()
    ? input
    : null;
}

function nonEmptyString(input: unknown): input is string {
  return typeof input === 'string' && input.length > 0 && input === input.trim();
}

function stableReasonCode(input: unknown): input is string {
  return nonEmptyString(input) && /^[a-z0-9]+(?:_[a-z0-9]+)*$/u.test(input);
}

function isRecord(input: unknown): input is Record<string, unknown> {
  return input !== null && typeof input === 'object' && !Array.isArray(input);
}

class AuthorityContractError extends Error {}
