import type {
  CreateTenantAgentBindingInput,
  TenantAgentBinding,
  TenantAgentBindingDefinition,
  TenantAgentBindingTestResult,
  TenantAgentBindingsAction,
  TenantAgentBindingsScope,
  TenantAgentBindingsSnapshot,
  TestTenantAgentBindingInput,
} from '../features/tenant/tenantAgentBindingsClient';

import { tenantAgentBindingsContractErrorV2 } from './desktopTenantAgentBindingsContractV2';

const CONTRACT_VERSION_V2 = '3.0.0';
const READ_ACTIONS_V2 = Object.freeze<TenantAgentBindingsAction[]>(['view', 'list']);
const MUTATION_ACTIONS_V2 = Object.freeze<TenantAgentBindingsAction[]>([
  'create',
  'delete',
  'set-enabled',
]);

export function projectDesktopTenantAgentBindingsCloudSnapshotV2(
  rawBindings: unknown,
  rawDefinitions: unknown,
  rawContext: unknown,
  scope: TenantAgentBindingsScope,
): TenantAgentBindingsSnapshot {
  const reason = 'cloud_tenant_agent_bindings_contract_invalid';
  if (!Array.isArray(rawBindings)) throw tenantAgentBindingsContractErrorV2(reason);
  const definitions = readDefinitionsV2(rawDefinitions, scope, reason);
  const definitionNames = new Map(
    definitions.map((definition) => [definition.id, definition.displayName]),
  );
  const authority = readCloudAuthorityV2(rawContext, scope, reason);
  const allowedActions = [
    ...READ_ACTIONS_V2,
    ...(authority.canManage ? MUTATION_ACTIONS_V2 : []),
    'test' as const,
  ];
  return Object.freeze({
    scope: Object.freeze({ ...scope }),
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: CONTRACT_VERSION_V2,
    allowedActions: Object.freeze(allowedActions),
    authorityRevision: authority.revision,
    bindings: Object.freeze(
      rawBindings.map((binding) =>
        projectDesktopTenantAgentBindingV2(binding, scope, definitionNames, reason),
      ),
    ),
    definitions,
  });
}

export function projectDesktopTenantAgentBindingsLocalSnapshotV2(
  payload: unknown,
  scope: TenantAgentBindingsScope,
): TenantAgentBindingsSnapshot {
  const reason = 'local_tenant_agent_bindings_contract_invalid';
  if (
    !isRecordV2(payload) ||
    payload.capability !== 'tenant_agent_bindings' ||
    !isAvailabilityV2(payload.availability) ||
    !isNullableReasonV2(payload.reason_code) ||
    !isNonemptyV2(payload.service_version) ||
    !isNonemptyV2(payload.contract_version) ||
    !isActionArrayV2(payload.allowed_actions) ||
    !isRecordV2(payload.scope) ||
    payload.scope.tenant_id !== scope.tenantId ||
    payload.scope.project_id !== null ||
    payload.scope.workspace_id !== null ||
    payload.scope.instance_id !== null ||
    !isNonnegativeIntegerV2(payload.authority_revision) ||
    !Array.isArray(payload.bindings) ||
    !Array.isArray(payload.definitions)
  ) {
    throw tenantAgentBindingsContractErrorV2(reason);
  }
  if (
    payload.availability === 'unavailable' &&
    (payload.allowed_actions.length !== 0 ||
      payload.bindings.length !== 0 ||
      payload.definitions.length !== 0)
  ) {
    throw tenantAgentBindingsContractErrorV2(reason);
  }
  const definitions = readDefinitionsV2(payload.definitions, scope, reason);
  const definitionNames = new Map(
    definitions.map((definition) => [definition.id, definition.displayName]),
  );
  return Object.freeze({
    scope: Object.freeze({ ...scope }),
    authority: 'local',
    availability: payload.availability,
    reasonCode: payload.reason_code,
    serviceVersion: payload.service_version,
    contractVersion: payload.contract_version,
    allowedActions: Object.freeze([...payload.allowed_actions]),
    authorityRevision: payload.authority_revision,
    bindings: Object.freeze(
      payload.bindings.map((binding) =>
        projectDesktopTenantAgentBindingV2(binding, scope, definitionNames, reason),
      ),
    ),
    definitions,
  });
}

export function projectDesktopTenantAgentBindingV2(
  payload: unknown,
  scope: TenantAgentBindingsScope,
  definitionNames: ReadonlyMap<string, string> = new Map(),
  reason = `${scope.authority}_tenant_agent_bindings_contract_invalid`,
): TenantAgentBinding {
  if (
    !isRecordV2(payload) ||
    !isNonemptyV2(payload.id) ||
    payload.tenant_id !== scope.tenantId ||
    !isNonemptyV2(payload.agent_id) ||
    !isNullableStringV2(payload.channel_type) ||
    !isNullableStringV2(payload.channel_id) ||
    !isNullableStringV2(payload.account_id) ||
    !isNullableStringV2(payload.peer_id) ||
    !isNullableStringV2(payload.group_id) ||
    !isIntegerV2(payload.priority) ||
    typeof payload.enabled !== 'boolean' ||
    !isNonemptyV2(payload.created_at) ||
    !isNonnegativeIntegerV2(payload.specificity_score)
  ) {
    throw tenantAgentBindingsContractErrorV2(reason);
  }
  return Object.freeze({
    id: payload.id,
    tenantId: scope.tenantId,
    agentId: payload.agent_id,
    agentName: definitionNames.get(payload.agent_id) ?? payload.agent_id,
    channelType: payload.channel_type,
    channelId: payload.channel_id,
    accountId: payload.account_id,
    peerId: payload.peer_id,
    groupId: payload.group_id,
    priority: payload.priority,
    enabled: payload.enabled,
    createdAt: payload.created_at,
    specificityScore: payload.specificity_score,
  });
}

export function projectDesktopTenantAgentBindingTestResultV2(
  payload: unknown,
  reason: string,
): TenantAgentBindingTestResult {
  if (
    !isRecordV2(payload) ||
    !isNullableStringV2(payload.agent_id) ||
    !isNullableStringV2(payload.agent_name) ||
    !isNullableStringV2(payload.binding_id) ||
    !isNonnegativeIntegerV2(payload.specificity_score) ||
    !isFiniteUnitNumberV2(payload.confidence) ||
    typeof payload.matched !== 'boolean' ||
    !Array.isArray(payload.trace)
  ) {
    throw tenantAgentBindingsContractErrorV2(reason);
  }
  return Object.freeze({
    agentId: payload.agent_id,
    agentName: payload.agent_name,
    bindingId: payload.binding_id,
    specificityScore: payload.specificity_score,
    confidence: payload.confidence,
    matched: payload.matched,
    trace: Object.freeze(
      payload.trace.map((entry) => {
        if (
          !isRecordV2(entry) ||
          !isNonemptyV2(entry.binding_id) ||
          !isNonemptyV2(entry.agent_id) ||
          !isNonnegativeIntegerV2(entry.specificity_score) ||
          !isNullableStringV2(entry.channel_type) ||
          !isNullableStringV2(entry.channel_id) ||
          !isNullableStringV2(entry.account_id) ||
          !isNullableStringV2(entry.peer_id) ||
          !isIntegerV2(entry.priority) ||
          typeof entry.eliminated !== 'boolean' ||
          !isNullableStringV2(entry.elimination_reason) ||
          typeof entry.selected !== 'boolean'
        ) {
          throw tenantAgentBindingsContractErrorV2(reason);
        }
        return Object.freeze({
          bindingId: entry.binding_id,
          agentId: entry.agent_id,
          specificityScore: entry.specificity_score,
          channelType: entry.channel_type,
          channelId: entry.channel_id,
          accountId: entry.account_id,
          peerId: entry.peer_id,
          priority: entry.priority,
          eliminated: entry.eliminated,
          eliminationReason: entry.elimination_reason,
          selected: entry.selected,
        });
      }),
    ),
  });
}

export function desktopTenantAgentBindingCreateBodyV2(
  input: CreateTenantAgentBindingInput,
): Readonly<Record<string, unknown>> {
  return compactV2({
    agent_id: input.agentId,
    channel_type: optionalValueV2(input.channelType),
    channel_id: optionalValueV2(input.channelId),
    account_id: optionalValueV2(input.accountId),
    peer_id: optionalValueV2(input.peerId),
    group_id: optionalValueV2(input.groupId),
    priority: input.priority,
  });
}

export function desktopTenantAgentBindingTestBodyV2(
  input: TestTenantAgentBindingInput,
): Readonly<Record<string, unknown>> {
  return compactV2({
    channel_type: input.channelType,
    channel_id: optionalValueV2(input.channelId),
    account_id: optionalValueV2(input.accountId),
    peer_id: optionalValueV2(input.peerId),
  });
}

function readDefinitionsV2(
  payload: unknown,
  scope: TenantAgentBindingsScope,
  reason: string,
): readonly TenantAgentBindingDefinition[] {
  const values =
    Array.isArray(payload)
      ? payload
      : isRecordV2(payload) && Array.isArray(payload.definitions)
        ? payload.definitions
        : null;
  if (values === null) throw tenantAgentBindingsContractErrorV2(reason);
  return Object.freeze(
    values.map((value) => {
      if (
        !isRecordV2(value) ||
        !isNonemptyV2(value.id) ||
        value.tenant_id !== scope.tenantId ||
        value.project_id !== null ||
        !isNonemptyV2(value.name) ||
        !isNullableStringV2(value.display_name) ||
        value.enabled !== true
      ) {
        throw tenantAgentBindingsContractErrorV2(reason);
      }
      return Object.freeze({
        id: value.id,
        name: value.name,
        displayName: value.display_name?.trim() || value.name,
      });
    }),
  );
}

function readCloudAuthorityV2(
  payload: unknown,
  scope: TenantAgentBindingsScope,
  reason: string,
): Readonly<{ revision: number; canManage: boolean }> {
  if (
    !isRecordV2(payload) ||
    !isRecordV2(payload.context) ||
    payload.context.tenant_id !== scope.tenantId ||
    !isNonnegativeIntegerV2(payload.context.revision) ||
    !isNonemptyV2(payload.membership_role)
  ) {
    throw tenantAgentBindingsContractErrorV2(reason);
  }
  return Object.freeze({
    revision: payload.context.revision,
    canManage: payload.membership_role === 'admin' || payload.membership_role === 'owner',
  });
}

function compactV2(
  input: Readonly<Record<string, unknown>>,
): Readonly<Record<string, unknown>> {
  return Object.freeze(
    Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined)),
  );
}

function optionalValueV2(value: string | null): string | undefined {
  return value?.trim() || undefined;
}

function isAvailabilityV2(
  value: unknown,
): value is TenantAgentBindingsSnapshot['availability'] {
  return (
    value === 'available' ||
    value === 'degraded' ||
    value === 'unavailable' ||
    value === 'not_applicable'
  );
}

function isActionArrayV2(value: unknown): value is TenantAgentBindingsAction[] {
  return (
    Array.isArray(value) &&
    value.every(
      (action) =>
        action === 'view' ||
        action === 'list' ||
        action === 'create' ||
        action === 'delete' ||
        action === 'set-enabled' ||
        action === 'test',
    )
  );
}

function isRecordV2(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isNonemptyV2(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isNullableStringV2(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isNullableReasonV2(value: unknown): value is string | null {
  return value === null || isNonemptyV2(value);
}

function isNonnegativeIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function isIntegerV2(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

function isFiniteUnitNumberV2(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
}
