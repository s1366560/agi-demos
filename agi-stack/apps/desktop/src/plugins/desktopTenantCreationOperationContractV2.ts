import { RuntimeV2Error } from '@agistack/plugin-runtime';

import {
  isTenantCreationPlan,
  validateTenantCreationDraft,
  type TenantCreationInput,
  type TenantCreationRecord,
} from '../features/tenant-creation/tenantCreationModel';
import { TenantCreationError } from '../features/tenant-creation/tenantCreationClient';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopTenantCreationOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  input: TenantCreationInput;
  signal?: AbortSignal;
}>;

export type PreparedDesktopTenantCreationOperationV2 = DesktopTenantCreationOperationInputV2;

const INPUT_KEYS_V2 = new Set(['config', 'input', 'signal']);
const RECORD_KEYS_V2 = new Set([
  'id', 'name', 'slug', 'description', 'owner_id', 'plan', 'max_projects',
  'max_users', 'max_storage', 'created_at', 'updated_at',
]);

export function prepareDesktopTenantCreationOperationV2(
  value: DesktopTenantCreationOperationInputV2,
): PreparedDesktopTenantCreationOperationV2 {
  if (!isPlainRecordV2(value) || !hasAllowedKeysV2(value, INPUT_KEYS_V2) ||
      !Object.hasOwn(value, 'config') || !Object.hasOwn(value, 'input') ||
      (value.signal !== undefined && !isAbortSignalV2(value.signal))) {
    throw invalidInputV2();
  }
  const config = cloneDesktopTenantCreationRuntimeConfigV2(value.config);
  if (config.mode !== 'cloud') {
    throw new TenantCreationError('local_tenant_creation_not_applicable');
  }
  if (!isPlainRecordV2(value.input)) throw invalidInputV2();
  const validation = validateTenantCreationDraft(value.input as TenantCreationInput);
  if (!validation.valid) throw new TenantCreationError(validation.reasonCode);
  return Object.freeze({
    config,
    input: validation.value,
    ...(value.signal === undefined ? {} : { signal: value.signal }),
  });
}

export function cloneDesktopTenantCreationRuntimeConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidInputV2();
  const copy = Object.freeze({ ...config });
  if (Object.values(copy).some((item) => typeof item !== 'string') ||
      (copy.mode !== 'cloud' && copy.mode !== 'local') || !copy.apiBaseUrl.trim()) {
    throw invalidInputV2();
  }
  return copy;
}

export function requireDesktopTenantCreationRecordV2(value: unknown): TenantCreationRecord {
  if (!isPlainRecordV2(value) || !hasExactKeysV2(value, RECORD_KEYS_V2) ||
      !nonemptyV2(value.id) || !nonemptyV2(value.name) || !nonemptyV2(value.slug) ||
      (value.description !== null && typeof value.description !== 'string') ||
      !nonemptyV2(value.owner_id) || typeof value.plan !== 'string' ||
      !isTenantCreationPlan(value.plan) || !positiveIntegerV2(value.max_projects) ||
      !positiveIntegerV2(value.max_users) || !nonnegativeIntegerV2(value.max_storage) ||
      !nonemptyV2(value.created_at) ||
      (value.updated_at !== null && !nonemptyV2(value.updated_at))) {
    throw new RuntimeV2Error(
      'desktop_tenant_creation_service_contract_invalid',
      'desktop tenant creation service returned an invalid record',
    );
  }
  return Object.freeze({ ...value }) as TenantCreationRecord;
}

function invalidInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_creation_operation_input_invalid',
    'desktop tenant creation operation input is invalid',
  );
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}
function hasAllowedKeysV2(value: Record<string, unknown>, keys: ReadonlySet<string>): boolean {
  return Object.keys(value).every((key) => keys.has(key));
}
function hasExactKeysV2(value: Record<string, unknown>, keys: ReadonlySet<string>): boolean {
  return Object.keys(value).length === keys.size && hasAllowedKeysV2(value, keys);
}
function isAbortSignalV2(value: unknown): value is AbortSignal {
  return typeof value === 'object' && value !== null &&
    typeof (value as AbortSignal).aborted === 'boolean' &&
    typeof (value as AbortSignal).addEventListener === 'function';
}
function nonemptyV2(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}
function positiveIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}
function nonnegativeIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}
