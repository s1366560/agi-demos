import { DesktopApiError } from '../../api/client';
import type { DesktopRuntimeConfig, RuntimeMode } from '../../types';
import type { DesktopCapabilityAvailability } from '../runtime/capabilitySnapshot';
import {
  createTenantAcpClient,
  TENANT_ACP_LOCAL_REASON,
  TENANT_ACP_ROUTE_ID,
  type TenantAcpClient,
} from './tenantAcpClient';
import {
  createTenantDecisionRecordsClient,
  TENANT_DECISION_RECORDS_LOCAL_REASON,
  TENANT_DECISION_RECORDS_ROUTE_ID,
  type TenantDecisionRecordsClient,
} from './tenantDecisionRecordsClient';
import {
  createTenantEventsClient,
  TENANT_EVENTS_LOCAL_REASON,
  TENANT_EVENTS_ROUTE_ID,
  type TenantEventsClient,
} from './tenantEventsClient';
import {
  createTenantGenesClient,
  TENANT_GENES_LOCAL_REASON,
  TENANT_GENES_ROUTE_ID,
  type TenantGenesClient,
} from './tenantGenesClient';
import {
  createTenantOrganizationSettingsClient,
  TENANT_ORGANIZATION_SETTINGS_LOCAL_REASON,
  TENANT_ORGANIZATION_SETTINGS_ROUTE_ID,
  type TenantOrganizationSettingsClient,
} from './tenantOrganizationSettingsClient';
import {
  createTenantPatternsClient,
  TENANT_PATTERNS_LOCAL_REASON,
  TENANT_PATTERNS_ROUTE_ID,
  type TenantPatternsClient,
} from './tenantPatternsClient';
import {
  createTenantSettingsClient,
  TENANT_SETTINGS_LOCAL_REASON,
  TENANT_SETTINGS_ROUTE_ID,
  type TenantSettingsClient,
} from './tenantSettingsClient';
import {
  createTenantWebhooksClient,
  TENANT_WEBHOOKS_LOCAL_REASON,
  TENANT_WEBHOOKS_ROUTE_ID,
  type TenantWebhooksClient,
} from './tenantWebhooksClient';

const SERVICE_VERSION = '0.1.0' as const;
const CONTRACT_VERSION = '4.0.0' as const;

export const TENANT_REMAINING_CAPABILITY_IDS = Object.freeze([
  TENANT_PATTERNS_ROUTE_ID,
  TENANT_ACP_ROUTE_ID,
  TENANT_WEBHOOKS_ROUTE_ID,
  TENANT_GENES_ROUTE_ID,
  TENANT_EVENTS_ROUTE_ID,
  TENANT_DECISION_RECORDS_ROUTE_ID,
  TENANT_ORGANIZATION_SETTINGS_ROUTE_ID,
  TENANT_SETTINGS_ROUTE_ID,
]);

export type TenantRemainingCapabilityId =
  (typeof TENANT_REMAINING_CAPABILITY_IDS)[number];
export type TenantRemainingCapabilitySet = Readonly<
  Record<TenantRemainingCapabilityId, DesktopCapabilityAvailability>
>;
export type TenantRemainingCapabilityClient = Readonly<{
  load(signal?: AbortSignal): Promise<TenantRemainingCapabilitySet>;
}>;
export type TenantRemainingCapabilityDependencies = Readonly<{
  patterns?: Pick<TenantPatternsClient, 'load'>;
  acp?: Pick<TenantAcpClient, 'load'>;
  webhooks?: Pick<TenantWebhooksClient, 'load'>;
  genes?: Pick<TenantGenesClient, 'load'>;
  events?: Pick<TenantEventsClient, 'load'>;
  decisionRecords?: Pick<TenantDecisionRecordsClient, 'load'>;
  organizationSettings?: Pick<TenantOrganizationSettingsClient, 'load'>;
  settings?: Pick<TenantSettingsClient, 'load'>;
}>;

const REASON_PREFIX = Object.freeze({
  [TENANT_PATTERNS_ROUTE_ID]: 'tenant_patterns',
  [TENANT_ACP_ROUTE_ID]: 'tenant_acp',
  [TENANT_WEBHOOKS_ROUTE_ID]: 'tenant_webhooks',
  [TENANT_GENES_ROUTE_ID]: 'tenant_genes',
  [TENANT_EVENTS_ROUTE_ID]: 'tenant_events',
  [TENANT_DECISION_RECORDS_ROUTE_ID]: 'tenant_decisions',
  [TENANT_ORGANIZATION_SETTINGS_ROUTE_ID]: 'tenant_org_settings',
  [TENANT_SETTINGS_ROUTE_ID]: 'tenant_settings',
} satisfies Record<TenantRemainingCapabilityId, string>);

const LOCAL_REASON = Object.freeze({
  [TENANT_PATTERNS_ROUTE_ID]: TENANT_PATTERNS_LOCAL_REASON,
  [TENANT_ACP_ROUTE_ID]: TENANT_ACP_LOCAL_REASON,
  [TENANT_WEBHOOKS_ROUTE_ID]: TENANT_WEBHOOKS_LOCAL_REASON,
  [TENANT_GENES_ROUTE_ID]: TENANT_GENES_LOCAL_REASON,
  [TENANT_EVENTS_ROUTE_ID]: TENANT_EVENTS_LOCAL_REASON,
  [TENANT_DECISION_RECORDS_ROUTE_ID]: TENANT_DECISION_RECORDS_LOCAL_REASON,
  [TENANT_ORGANIZATION_SETTINGS_ROUTE_ID]: TENANT_ORGANIZATION_SETTINGS_LOCAL_REASON,
  [TENANT_SETTINGS_ROUTE_ID]: TENANT_SETTINGS_LOCAL_REASON,
} satisfies Record<TenantRemainingCapabilityId, string>);

const ACTION_CATALOG = Object.freeze({
  [TENANT_PATTERNS_ROUTE_ID]: Object.freeze(['view', 'list', 'delete']),
  [TENANT_ACP_ROUTE_ID]: Object.freeze([
    'view',
    'view-status',
    'list-runner-pools',
    'list-agents',
    'list-sessions',
    'create-agent',
    'update-agent',
    'delete-agent',
    'test-agent',
  ]),
  [TENANT_WEBHOOKS_ROUTE_ID]: Object.freeze([
    'view',
    'list',
    'list-event-types',
    'create',
    'update',
    'delete',
    'copy-secret',
  ]),
  [TENANT_GENES_ROUTE_ID]: Object.freeze([
    'view',
    'list',
    'inspect-genome',
    'inspect-evolution',
    'list-reviews',
    'rate',
    'create-review',
    'delete-own-review',
    'create',
    'update',
    'delete',
    'publish',
    'unpublish',
    'install',
  ]),
  [TENANT_EVENTS_ROUTE_ID]: Object.freeze(['view', 'list', 'filter', 'paginate']),
  [TENANT_DECISION_RECORDS_ROUTE_ID]: Object.freeze([
    'view',
    'list',
    'filter',
    'inspect',
    'resolve-approval',
  ]),
  [TENANT_ORGANIZATION_SETTINGS_ROUTE_ID]: Object.freeze([
    'view',
    'inspect-stats',
    'inspect-smtp',
    'manage-registries',
    'update-smtp',
    'delete-smtp',
    'test-smtp',
    'manage-gene-policies',
  ]),
  [TENANT_SETTINGS_ROUTE_ID]: Object.freeze([
    'view',
    'inspect-usage',
    'update',
    'delete',
  ]),
} satisfies Record<TenantRemainingCapabilityId, readonly string[]>);

export function createTenantRemainingCapabilityClient(
  config: DesktopRuntimeConfig,
  dependencies: TenantRemainingCapabilityDependencies = {},
): TenantRemainingCapabilityClient {
  const runtimeConfig = Object.freeze({ ...config });
  const clients = Object.freeze({
    patterns: dependencies.patterns ?? createTenantPatternsClient(runtimeConfig),
    acp: dependencies.acp ?? createTenantAcpClient(runtimeConfig),
    webhooks: dependencies.webhooks ?? createTenantWebhooksClient(runtimeConfig),
    genes: dependencies.genes ?? createTenantGenesClient(runtimeConfig),
    events: dependencies.events ?? createTenantEventsClient(runtimeConfig),
    decisionRecords:
      dependencies.decisionRecords ?? createTenantDecisionRecordsClient(runtimeConfig),
    organizationSettings:
      dependencies.organizationSettings ??
      createTenantOrganizationSettingsClient(runtimeConfig),
    settings: dependencies.settings ?? createTenantSettingsClient(runtimeConfig),
  });

  return Object.freeze({
    async load(signal?: AbortSignal): Promise<TenantRemainingCapabilitySet> {
      const tenantId = identifier(runtimeConfig.tenantId);
      if (!tenantId) {
        return capabilitySet((id) =>
          declaredUnavailable(`${REASON_PREFIX[id]}_scope_unavailable`, null),
        );
      }
      const scope = Object.freeze({ authority: runtimeConfig.mode, tenantId });
      if (runtimeConfig.mode === 'local') {
        const [patterns, genes, events] = await Promise.all([
          observeCapability(
            TENANT_PATTERNS_ROUTE_ID,
            runtimeConfig.mode,
            () => clients.patterns.load(scope, { signal }),
            tenantId,
            null,
            signal,
          ),
          observeCapability(
            TENANT_GENES_ROUTE_ID,
            runtimeConfig.mode,
            () => clients.genes.load(scope, { signal }),
            tenantId,
            null,
            signal,
          ),
          observeCapability(
            TENANT_EVENTS_ROUTE_ID,
            runtimeConfig.mode,
            () => clients.events.load(scope, { signal }),
            tenantId,
            null,
            signal,
          ),
        ]);
        return Object.freeze({
          [TENANT_PATTERNS_ROUTE_ID]: patterns,
          [TENANT_ACP_ROUTE_ID]: notApplicable(TENANT_ACP_LOCAL_REASON, tenantId),
          [TENANT_WEBHOOKS_ROUTE_ID]: notApplicable(
            TENANT_WEBHOOKS_LOCAL_REASON,
            tenantId,
          ),
          [TENANT_GENES_ROUTE_ID]: genes,
          [TENANT_EVENTS_ROUTE_ID]: events,
          [TENANT_DECISION_RECORDS_ROUTE_ID]: notApplicable(
            TENANT_DECISION_RECORDS_LOCAL_REASON,
            tenantId,
          ),
          [TENANT_ORGANIZATION_SETTINGS_ROUTE_ID]: notApplicable(
            TENANT_ORGANIZATION_SETTINGS_LOCAL_REASON,
            tenantId,
          ),
          [TENANT_SETTINGS_ROUTE_ID]: notApplicable(TENANT_SETTINGS_LOCAL_REASON, tenantId),
        });
      }

      const workspaceId = identifier(runtimeConfig.workspaceId);
      const [
        patterns,
        acp,
        webhooks,
        genes,
        events,
        decisionRecords,
        organizationSettings,
        settings,
      ] = await Promise.all([
          observeCapability(
            TENANT_PATTERNS_ROUTE_ID,
            runtimeConfig.mode,
            () => clients.patterns.load(scope, { signal }),
            tenantId,
            null,
            signal,
          ),
          observeCapability(
            TENANT_ACP_ROUTE_ID,
            runtimeConfig.mode,
            () => clients.acp.load(scope, { signal }),
            tenantId,
            null,
            signal,
          ),
          observeCapability(
            TENANT_WEBHOOKS_ROUTE_ID,
            runtimeConfig.mode,
            () => clients.webhooks.load(scope, { signal }),
            tenantId,
            null,
            signal,
          ),
          observeCapability(
            TENANT_GENES_ROUTE_ID,
            runtimeConfig.mode,
            () => clients.genes.load(scope, { signal }),
            tenantId,
            null,
            signal,
          ),
          observeCapability(
            TENANT_EVENTS_ROUTE_ID,
            runtimeConfig.mode,
            () => clients.events.load(scope, { signal }),
            tenantId,
            null,
            signal,
          ),
          workspaceId
            ? observeCapability(
                TENANT_DECISION_RECORDS_ROUTE_ID,
                runtimeConfig.mode,
                () =>
                  clients.decisionRecords.load(
                    Object.freeze({ ...scope, workspaceId }),
                    { signal },
                  ),
                tenantId,
                workspaceId,
                signal,
              )
            : Promise.resolve(
                declaredUnavailable(
                  'tenant_decisions_workspace_scope_unavailable',
                  tenantId,
                ),
              ),
          observeCapability(
            TENANT_ORGANIZATION_SETTINGS_ROUTE_ID,
            runtimeConfig.mode,
            () => clients.organizationSettings.load(scope, { signal }),
            tenantId,
            null,
            signal,
          ),
          observeCapability(
            TENANT_SETTINGS_ROUTE_ID,
            runtimeConfig.mode,
            () => clients.settings.load(scope, { signal }),
            tenantId,
            null,
            signal,
          ),
        ]);
      return Object.freeze({
        [TENANT_PATTERNS_ROUTE_ID]: patterns,
        [TENANT_ACP_ROUTE_ID]: acp,
        [TENANT_WEBHOOKS_ROUTE_ID]: webhooks,
        [TENANT_GENES_ROUTE_ID]: genes,
        [TENANT_EVENTS_ROUTE_ID]: events,
        [TENANT_DECISION_RECORDS_ROUTE_ID]: decisionRecords,
        [TENANT_ORGANIZATION_SETTINGS_ROUTE_ID]: organizationSettings,
        [TENANT_SETTINGS_ROUTE_ID]: settings,
      });
    },
  });
}

async function observeCapability(
  id: TenantRemainingCapabilityId,
  mode: RuntimeMode,
  load: () => Promise<unknown>,
  tenantId: string,
  workspaceId: string | null,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  try {
    return normalizeObservation(id, mode, await load(), tenantId, workspaceId);
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error instanceof AuthorityContractError) {
      return observedUnavailable(
        `${REASON_PREFIX[id]}_authority_contract_invalid`,
        mode,
        tenantId,
        workspaceId,
      );
    }
    if (error instanceof DesktopApiError && error.status === 403) {
      return observedUnavailable(
        `${REASON_PREFIX[id]}_forbidden`,
        mode,
        tenantId,
        workspaceId,
      );
    }
    if (error instanceof DesktopApiError && error.status === 409) {
      return observedUnavailable(
        `${REASON_PREFIX[id]}_scope_conflict`,
        mode,
        tenantId,
        workspaceId,
      );
    }
    return observedUnavailable(
      mode === 'local' ? LOCAL_REASON[id] : `${REASON_PREFIX[id]}_authority_unavailable`,
      mode,
      tenantId,
      workspaceId,
    );
  }
}

function normalizeObservation(
  id: TenantRemainingCapabilityId,
  mode: RuntimeMode,
  input: unknown,
  tenantId: string,
  workspaceId: string | null,
): DesktopCapabilityAvailability {
  if (!isRecord(input) || !isRecord(input.scope)) throw new AuthorityContractError();
  const expectedAuthority = mode === 'local' ? 'sidecar' : 'cloud';
  if (
    input.authority !== expectedAuthority ||
    input.scope.authority !== mode ||
    input.scope.tenantId !== tenantId ||
    (workspaceId !== null && input.scope.workspaceId !== workspaceId) ||
    (workspaceId === null &&
      'workspaceId' in input.scope &&
      input.scope.workspaceId !== null &&
      input.scope.workspaceId !== undefined)
  ) {
    throw new AuthorityContractError();
  }
  if (input.availability !== 'available' && input.availability !== 'degraded') {
    throw new AuthorityContractError();
  }
  const reasonCode = input.reasonCode;
  if (
    (input.availability === 'available' && reasonCode !== null) ||
    (input.availability === 'degraded' && !stableReasonCode(reasonCode)) ||
    input.contractVersion !== CONTRACT_VERSION ||
    !Number.isSafeInteger(input.scopeRevision) ||
    Number(input.scopeRevision) < 0 ||
    !orderedActionSubset(id, input.allowedActions)
  ) {
    throw new AuthorityContractError();
  }
  return Object.freeze({
    availability: input.availability,
    reason_code: reasonCode as string | null,
    service_version: SERVICE_VERSION,
    contract_version: CONTRACT_VERSION,
    allowed_actions: Object.freeze([...(input.allowedActions as string[])]),
    scope: capabilityScope(tenantId, workspaceId),
    authority_revision: Number(input.scopeRevision),
    authority_source: mode === 'local' ? 'sidecar' : 'cloud_service',
    provenance: 'observed',
  });
}

function capabilitySet(
  build: (id: TenantRemainingCapabilityId) => DesktopCapabilityAvailability,
): TenantRemainingCapabilitySet {
  return Object.freeze({
    [TENANT_PATTERNS_ROUTE_ID]: build(TENANT_PATTERNS_ROUTE_ID),
    [TENANT_ACP_ROUTE_ID]: build(TENANT_ACP_ROUTE_ID),
    [TENANT_WEBHOOKS_ROUTE_ID]: build(TENANT_WEBHOOKS_ROUTE_ID),
    [TENANT_GENES_ROUTE_ID]: build(TENANT_GENES_ROUTE_ID),
    [TENANT_EVENTS_ROUTE_ID]: build(TENANT_EVENTS_ROUTE_ID),
    [TENANT_DECISION_RECORDS_ROUTE_ID]: build(TENANT_DECISION_RECORDS_ROUTE_ID),
    [TENANT_ORGANIZATION_SETTINGS_ROUTE_ID]: build(
      TENANT_ORGANIZATION_SETTINGS_ROUTE_ID,
    ),
    [TENANT_SETTINGS_ROUTE_ID]: build(TENANT_SETTINGS_ROUTE_ID),
  });
}

function notApplicable(reasonCode: string, tenantId: string): DesktopCapabilityAvailability {
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

function declaredUnavailable(
  reasonCode: string,
  tenantId: string | null,
): DesktopCapabilityAvailability {
  return Object.freeze({
    availability: 'unavailable',
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

function observedUnavailable(
  reasonCode: string,
  mode: RuntimeMode,
  tenantId: string,
  workspaceId: string | null,
): DesktopCapabilityAvailability {
  return Object.freeze({
    availability: 'unavailable',
    reason_code: reasonCode,
    service_version: null,
    contract_version: null,
    allowed_actions: Object.freeze([]),
    scope: capabilityScope(tenantId, workspaceId),
    authority_revision: null,
    authority_source: mode === 'local' ? 'sidecar' : 'cloud_service',
    provenance: 'observed',
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

function orderedActionSubset(id: TenantRemainingCapabilityId, input: unknown): input is string[] {
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

function stableReasonCode(input: unknown): input is string {
  return typeof input === 'string' && /^[a-z0-9]+(?:_[a-z0-9]+)*$/u.test(input);
}

function isRecord(input: unknown): input is Record<string, unknown> {
  return input !== null && typeof input === 'object' && !Array.isArray(input);
}

class AuthorityContractError extends Error {}
