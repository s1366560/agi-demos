import { DesktopApiError } from '../api/client';
import type {
  TenantAgentBinding,
  TenantAgentBindingTestResult,
  TenantAgentBindingTraceEntry,
  TenantAgentBindingsAction,
  TenantAgentBindingsScope,
  TenantAgentBindingsSnapshot,
} from '../features/tenant/tenantAgentBindingsClient';

const ACTION_ORDER_V2 = Object.freeze<TenantAgentBindingsAction[]>([
  'view',
  'list',
  'create',
  'delete',
  'set-enabled',
  'test',
]);
const SNAPSHOT_KEYS_V2 = new Set([
  'scope',
  'authority',
  'availability',
  'reasonCode',
  'serviceVersion',
  'contractVersion',
  'allowedActions',
  'authorityRevision',
  'bindings',
  'definitions',
]);
const BINDING_KEYS_V2 = new Set([
  'id',
  'tenantId',
  'agentId',
  'agentName',
  'channelType',
  'channelId',
  'accountId',
  'peerId',
  'groupId',
  'priority',
  'enabled',
  'createdAt',
  'specificityScore',
]);
const TEST_RESULT_KEYS_V2 = new Set([
  'agentId',
  'agentName',
  'bindingId',
  'specificityScore',
  'confidence',
  'matched',
  'trace',
]);

export function requireDesktopTenantAgentBindingsSnapshotV2(
  value: unknown,
  expectedScope: TenantAgentBindingsScope,
): TenantAgentBindingsSnapshot {
  const reason = 'desktop_tenant_agent_bindings_service_contract_invalid';
  if (
    !isRecordV2(value) ||
    !hasExactKeysV2(value, SNAPSHOT_KEYS_V2) ||
    !isProjectedScopeV2(value.scope, expectedScope) ||
    value.authority !== expectedScope.authority ||
    !isAvailabilityV2(value.availability) ||
    !isNullableNonemptyV2(value.reasonCode) ||
    !isNonemptyV2(value.serviceVersion) ||
    !isNonemptyV2(value.contractVersion) ||
    !isOrderedActionSubsetV2(value.allowedActions) ||
    !isNullableNonnegativeIntegerV2(value.authorityRevision) ||
    !Array.isArray(value.bindings) ||
    !Array.isArray(value.definitions)
  ) {
    throw tenantAgentBindingsContractErrorV2(reason);
  }
  if (
    value.availability === 'unavailable' &&
    (value.allowedActions.length !== 0 ||
      value.bindings.length !== 0 ||
      value.definitions.length !== 0)
  ) {
    throw tenantAgentBindingsContractErrorV2(reason);
  }
  return Object.freeze({
    scope: Object.freeze({ ...expectedScope }),
    authority: expectedScope.authority,
    availability: value.availability,
    reasonCode: value.reasonCode,
    serviceVersion: value.serviceVersion,
    contractVersion: value.contractVersion,
    allowedActions: Object.freeze([...value.allowedActions]),
    authorityRevision: value.authorityRevision,
    bindings: Object.freeze(
      value.bindings.map((binding) =>
        requireDesktopTenantAgentBindingV2(binding, expectedScope, reason),
      ),
    ),
    definitions: Object.freeze(
      value.definitions.map((definition) => {
        if (
          !isRecordV2(definition) ||
          !hasExactKeysV2(definition, new Set(['id', 'name', 'displayName'])) ||
          !isNonemptyV2(definition.id) ||
          !isNonemptyV2(definition.name) ||
          !isNonemptyV2(definition.displayName)
        ) {
          throw tenantAgentBindingsContractErrorV2(reason);
        }
        return Object.freeze({
          id: definition.id,
          name: definition.name,
          displayName: definition.displayName,
        });
      }),
    ),
  });
}

export function requireDesktopTenantAgentBindingV2(
  value: unknown,
  expectedScope: TenantAgentBindingsScope,
  reason = 'desktop_tenant_agent_bindings_service_contract_invalid',
): TenantAgentBinding {
  if (
    !isRecordV2(value) ||
    !hasExactKeysV2(value, BINDING_KEYS_V2) ||
    !isNonemptyV2(value.id) ||
    value.tenantId !== expectedScope.tenantId ||
    !isNonemptyV2(value.agentId) ||
    !isNonemptyV2(value.agentName) ||
    !isNullableStringV2(value.channelType) ||
    !isNullableStringV2(value.channelId) ||
    !isNullableStringV2(value.accountId) ||
    !isNullableStringV2(value.peerId) ||
    !isNullableStringV2(value.groupId) ||
    !isIntegerV2(value.priority) ||
    typeof value.enabled !== 'boolean' ||
    !isNonemptyV2(value.createdAt) ||
    !isNonnegativeIntegerV2(value.specificityScore)
  ) {
    throw tenantAgentBindingsContractErrorV2(reason);
  }
  return Object.freeze({
    id: value.id,
    tenantId: value.tenantId,
    agentId: value.agentId,
    agentName: value.agentName,
    channelType: value.channelType,
    channelId: value.channelId,
    accountId: value.accountId,
    peerId: value.peerId,
    groupId: value.groupId,
    priority: value.priority,
    enabled: value.enabled,
    createdAt: value.createdAt,
    specificityScore: value.specificityScore,
  });
}

export function requireDesktopTenantAgentBindingTestResultV2(
  value: unknown,
): TenantAgentBindingTestResult {
  const reason = 'desktop_tenant_agent_bindings_service_contract_invalid';
  if (
    !isRecordV2(value) ||
    !hasExactKeysV2(value, TEST_RESULT_KEYS_V2) ||
    !isNullableStringV2(value.agentId) ||
    !isNullableStringV2(value.agentName) ||
    !isNullableStringV2(value.bindingId) ||
    !isNonnegativeIntegerV2(value.specificityScore) ||
    !isFiniteUnitNumberV2(value.confidence) ||
    typeof value.matched !== 'boolean' ||
    !Array.isArray(value.trace)
  ) {
    throw tenantAgentBindingsContractErrorV2(reason);
  }
  return Object.freeze({
    agentId: value.agentId,
    agentName: value.agentName,
    bindingId: value.bindingId,
    specificityScore: value.specificityScore,
    confidence: value.confidence,
    matched: value.matched,
    trace: Object.freeze(value.trace.map((entry) => requireTraceEntryV2(entry, reason))),
  });
}

export function tenantAgentBindingsContractErrorV2(reason: string): DesktopApiError {
  return new DesktopApiError(reason, 0, { reason_code: reason });
}

function requireTraceEntryV2(value: unknown, reason: string): TenantAgentBindingTraceEntry {
  if (
    !isRecordV2(value) ||
    !hasExactKeysV2(
      value,
      new Set([
        'bindingId',
        'agentId',
        'specificityScore',
        'channelType',
        'channelId',
        'accountId',
        'peerId',
        'priority',
        'eliminated',
        'eliminationReason',
        'selected',
      ]),
    ) ||
    !isNonemptyV2(value.bindingId) ||
    !isNonemptyV2(value.agentId) ||
    !isNonnegativeIntegerV2(value.specificityScore) ||
    !isNullableStringV2(value.channelType) ||
    !isNullableStringV2(value.channelId) ||
    !isNullableStringV2(value.accountId) ||
    !isNullableStringV2(value.peerId) ||
    !isIntegerV2(value.priority) ||
    typeof value.eliminated !== 'boolean' ||
    !isNullableStringV2(value.eliminationReason) ||
    typeof value.selected !== 'boolean'
  ) {
    throw tenantAgentBindingsContractErrorV2(reason);
  }
  return Object.freeze({
    bindingId: value.bindingId,
    agentId: value.agentId,
    specificityScore: value.specificityScore,
    channelType: value.channelType,
    channelId: value.channelId,
    accountId: value.accountId,
    peerId: value.peerId,
    priority: value.priority,
    eliminated: value.eliminated,
    eliminationReason: value.eliminationReason,
    selected: value.selected,
  });
}

function isProjectedScopeV2(
  value: unknown,
  expectedScope: TenantAgentBindingsScope,
): value is TenantAgentBindingsScope {
  return (
    isRecordV2(value) &&
    hasExactKeysV2(value, new Set(['authority', 'tenantId'])) &&
    value.authority === expectedScope.authority &&
    value.tenantId === expectedScope.tenantId
  );
}

function isOrderedActionSubsetV2(value: unknown): value is TenantAgentBindingsAction[] {
  if (!Array.isArray(value)) return false;
  let lastIndex = -1;
  for (const action of value) {
    const index = ACTION_ORDER_V2.indexOf(action as TenantAgentBindingsAction);
    if (index <= lastIndex) return false;
    lastIndex = index;
  }
  return true;
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

function hasExactKeysV2(
  value: Record<string, unknown>,
  expected: ReadonlySet<string>,
): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function isRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function isNonemptyV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isNullableStringV2(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isNullableNonemptyV2(value: unknown): value is string | null {
  return value === null || isNonemptyV2(value);
}

function isNullableNonnegativeIntegerV2(value: unknown): value is number | null {
  return value === null || isNonnegativeIntegerV2(value);
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
