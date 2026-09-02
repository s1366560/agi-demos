import { DesktopApiError } from '../api/client';
import type {
  TenantProjectRecord,
  TenantProjectsScope,
  TenantProjectsListSnapshot,
} from '../features/tenant/tenantProjectsClient';

type TenantProjectsAction = 'view' | 'list' | 'create' | 'update' | 'delete';

const ACTION_ORDER_V2 = Object.freeze<TenantProjectsAction[]>([
  'view',
  'list',
  'create',
  'update',
  'delete',
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
  'projects',
  'total',
  'page',
  'pageSize',
  'ownerIds',
]);
const PROJECT_KEYS_V2 = new Set([
  'id',
  'tenantId',
  'name',
  'description',
  'ownerId',
  'memberIds',
  'allowedActions',
  'isPublic',
  'createdAt',
  'updatedAt',
  'stats',
]);

export function requireDesktopTenantProjectsSnapshotV2(
  value: unknown,
  expectedScope: TenantProjectsScope,
): TenantProjectsListSnapshot {
  const reason = 'desktop_tenant_projects_service_contract_invalid';
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, SNAPSHOT_KEYS_V2) ||
    !isProjectedScopeV2(value.scope, expectedScope) ||
    value.authority !== expectedScope.authority ||
    !isAvailabilityV2(value.availability) ||
    !isNullableNonemptyV2(value.reasonCode) ||
    !isNonemptyV2(value.serviceVersion) ||
    !isNonemptyV2(value.contractVersion) ||
    !isOrderedActionSubsetV2(value.allowedActions) ||
    !isNullableNonnegativeIntegerV2(value.authorityRevision) ||
    !Array.isArray(value.projects) ||
    !isNonnegativeIntegerV2(value.total) ||
    !isPositiveIntegerV2(value.page) ||
    !isPositiveIntegerV2(value.pageSize) ||
    !isStringArrayV2(value.ownerIds)
  ) {
    throw tenantProjectsServiceContractErrorV2(reason);
  }
  if (
    value.availability === 'unavailable' &&
    (value.allowedActions.length !== 0 || value.projects.length !== 0)
  ) {
    throw tenantProjectsServiceContractErrorV2(reason);
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
    projects: Object.freeze(
      value.projects.map((project) =>
        requireDesktopTenantProjectRecordV2(project, expectedScope, reason),
      ),
    ),
    total: value.total,
    page: value.page,
    pageSize: value.pageSize,
    ownerIds: Object.freeze([...value.ownerIds]),
  });
}

export function requireDesktopTenantProjectRecordV2(
  value: unknown,
  expectedScope: TenantProjectsScope,
  reason = 'desktop_tenant_projects_service_contract_invalid',
): TenantProjectRecord {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, PROJECT_KEYS_V2) ||
    !isNonemptyV2(value.id) ||
    value.tenantId !== expectedScope.tenantId ||
    !isNonemptyV2(value.name) ||
    typeof value.description !== 'string' ||
    !isNonemptyV2(value.ownerId) ||
    !isStringArrayV2(value.memberIds) ||
    !isOrderedActionSubsetV2(value.allowedActions) ||
    typeof value.isPublic !== 'boolean' ||
    !isNonemptyV2(value.createdAt) ||
    !isNullableStringV2(value.updatedAt) ||
    !isPlainRecordV2(value.stats)
  ) {
    throw tenantProjectsServiceContractErrorV2(reason);
  }
  return Object.freeze({
    id: value.id,
    tenantId: expectedScope.tenantId,
    name: value.name,
    description: value.description,
    ownerId: value.ownerId,
    memberIds: Object.freeze([...value.memberIds]),
    allowedActions: Object.freeze([...value.allowedActions]),
    isPublic: value.isPublic,
    createdAt: value.createdAt,
    updatedAt: value.updatedAt,
    stats: Object.freeze({ ...value.stats }),
  });
}

export function tenantProjectsServiceContractErrorV2(reason: string): DesktopApiError {
  return new DesktopApiError(reason, 0, { reason_code: reason });
}

function isProjectedScopeV2(
  value: unknown,
  expectedScope: TenantProjectsScope,
): value is TenantProjectsScope {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, new Set(['authority', 'tenantId'])) &&
    value.authority === expectedScope.authority &&
    value.tenantId === expectedScope.tenantId
  );
}

function isOrderedActionSubsetV2(value: unknown): value is TenantProjectsAction[] {
  if (!Array.isArray(value)) return false;
  let lastIndex = -1;
  for (const action of value) {
    const index = ACTION_ORDER_V2.indexOf(action as TenantProjectsAction);
    if (index <= lastIndex) return false;
    lastIndex = index;
  }
  return true;
}

function isAvailabilityV2(
  value: unknown,
): value is TenantProjectsListSnapshot['availability'] {
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

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function isStringArrayV2(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isNonemptyV2);
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

function isPositiveIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

function isNonnegativeIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}
