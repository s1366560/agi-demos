import { digestV2 } from './canonical';
import {
  parsePluginManifestV2,
  validateManifestContractDigestsV2,
  validateManifestContractsV2,
} from './contract';
import { PluginProtocolV2Error } from './errors';
import type { ProfileEntryV2, ProfileSnapshotV2, QuotaV2, ScopeKindV2, ScopeV2 } from './generated';

export { PluginProtocolV2Error } from './errors';

export const PLUGIN_PROFILE_TYPE_URL_V2 = 'types.memstack.ai/plugin.profile.v2';

const ENTRY_ID = /^[a-z0-9][a-z0-9._-]{0,127}$/;
const MODULE_REF = /^[a-z][a-z0-9+.-]*:\/\/.+$/;
const SERVICE = /^service:[a-z0-9][a-z0-9._:-]{0,255}$/;
const ALIAS = /^[a-z][a-z0-9_]{0,127}$/;

export async function parseProfileSnapshotV2(value: unknown): Promise<ProfileSnapshotV2> {
  const payload = objectValue(value, 'snapshot');
  if (payload.schema_version !== 2) {
    throw new PluginProtocolV2Error(
      'incompatible_schema_version',
      'plugin snapshot schema_version must be 2; v1 is not accepted'
    );
  }
  exactKeys(payload, [
    'schema_version',
    'profile_id',
    'generation',
    'manifests',
    'entries',
    'digest',
  ]);
  const snapshot: ProfileSnapshotV2 = {
    schema_version: integerValue(payload.schema_version, 'schema_version'),
    profile_id: stringValue(payload.profile_id, 'profile_id'),
    generation: positiveInteger(payload.generation, 'generation'),
    manifests: arrayValue(payload.manifests, 'manifests').map(parsePluginManifestV2),
    entries: arrayValue(payload.entries, 'entries').map(parseEntry),
    digest: digestValue(payload.digest, 'digest'),
  };
  validateSemantics(snapshot);
  validateManifestContractsV2(snapshot.manifests);
  await validateManifestContractDigestsV2(snapshot.manifests);
  const { digest: _digest, ...digestPayload } = snapshot;
  const expected = await digestV2(digestPayload);
  if (snapshot.digest !== expected) {
    throw new PluginProtocolV2Error(
      'digest_mismatch',
      `snapshot digest mismatch: expected ${expected}`
    );
  }
  return snapshot;
}

function parseEntry(value: unknown, index: number): ProfileEntryV2 {
  const payload = objectValue(value, `entries[${index}]`);
  exactKeys(payload, [
    'entry_id',
    'parent_entry_id',
    'plugin_ref',
    'module_ref',
    'enabled',
    'config',
    'inject',
    'isolate',
    'scope',
    'permissions',
    'quotas',
    'restart_policy',
  ]);
  const inject = stringRecord(payload.inject, 'inject');
  for (const [alias, service] of Object.entries(inject)) {
    patternString(alias, ALIAS, `inject alias ${alias}`);
    patternString(service, SERVICE, `inject.${alias}`);
  }
  return {
    entry_id: patternString(payload.entry_id, ENTRY_ID, 'entry_id'),
    parent_entry_id: nullableString(payload.parent_entry_id, 'parent_entry_id'),
    plugin_ref: stringValue(payload.plugin_ref, 'plugin_ref'),
    module_ref: patternString(payload.module_ref, MODULE_REF, 'module_ref'),
    enabled: booleanValue(payload.enabled, 'enabled'),
    config: objectValue(payload.config, 'config'),
    inject,
    isolate: stringRecord(payload.isolate, 'isolate'),
    scope: parseScope(payload.scope),
    permissions: uniqueStrings(payload.permissions, 'permissions'),
    quotas: parseQuota(payload.quotas),
    restart_policy: enumValue(
      payload.restart_policy,
      ['hot-generation', 'process-boundary'] as const,
      'restart_policy'
    ),
  };
}

function parseScope(value: unknown): ScopeV2 {
  const payload = objectValue(value, 'scope');
  allowedKeys(payload, ['kind', 'tenant_id', 'project_id', 'session_id']);
  requiredKeys(payload, ['kind']);
  const scope: ScopeV2 = {
    kind: enumValue(payload.kind, ['root', 'tenant', 'project', 'session'] as const, 'scope.kind'),
    ...(payload.tenant_id === undefined
      ? {}
      : { tenant_id: nullableString(payload.tenant_id, 'scope.tenant_id') }),
    ...(payload.project_id === undefined
      ? {}
      : { project_id: nullableString(payload.project_id, 'scope.project_id') }),
    ...(payload.session_id === undefined
      ? {}
      : { session_id: nullableString(payload.session_id, 'scope.session_id') }),
  };
  validateScope(scope);
  return scope;
}

function parseQuota(value: unknown): QuotaV2 {
  const payload = objectValue(value, 'quotas');
  const keys = [
    'max_wasm_fuel',
    'max_wasm_memory_bytes',
    'max_wall_time_ms',
    'max_concurrent_calls',
    'max_output_bytes',
    'max_network_requests_per_minute',
    'max_storage_bytes',
    'max_monthly_usd_micros',
  ] as const;
  allowedKeys(payload, keys);
  return Object.fromEntries(
    Object.entries(payload).map(([key, item]) => [key, nonNegativeInteger(item, `quotas.${key}`)])
  ) as QuotaV2;
}

function validateSemantics(snapshot: ProfileSnapshotV2): void {
  const manifests = uniqueMap(snapshot.manifests, (item) => item.plugin_id, 'duplicate_plugin_id');
  const entries = uniqueMap(snapshot.entries, (item) => item.entry_id, 'duplicate_entry_id');
  for (const entry of snapshot.entries) validateEntry(entry, manifests, entries);
  for (const entry of snapshot.entries) {
    const visiting = new Set<string>();
    let cursor: ProfileEntryV2 | undefined = entry;
    while (cursor !== undefined && cursor.parent_entry_id !== null) {
      if (visiting.has(cursor.entry_id)) {
        fail('entry_cycle', `entry parent cycle includes ${cursor.entry_id}`);
      }
      visiting.add(cursor.entry_id);
      cursor = entries.get(cursor.parent_entry_id);
    }
  }
}

function validateEntry(
  entry: ProfileEntryV2,
  manifests: ReadonlyMap<string, ProfileSnapshotV2['manifests'][number]>,
  entries: ReadonlyMap<string, ProfileEntryV2>
): void {
  const manifest = manifests.get(entry.plugin_ref);
  if (!manifest) {
    fail(
      'missing_manifest',
      `entry ${entry.entry_id} references missing plugin ${entry.plugin_ref}`
    );
  }
  const module = manifest.modules.find((item) => item.module_ref === entry.module_ref);
  if (!module)
    fail('missing_module', `entry ${entry.entry_id} references a module outside its plugin`);
  if (entry.parent_entry_id === null) return;
  const parent = entries.get(entry.parent_entry_id);
  if (!parent) fail('missing_parent_entry', `entry ${entry.entry_id} has a missing parent`);
  if (!scopeContains(parent.scope, entry.scope)) {
    fail('invalid_parent_scope', `entry ${entry.entry_id} is outside its parent scope`);
  }
  const parentManifest = manifests.get(parent.plugin_ref);
  const parentModule = parentManifest?.modules.find(
    (item) => item.module_ref === parent.module_ref
  );
  if (!parentModule) {
    fail('missing_module', `parent ${parent.entry_id} references a module outside its plugin`);
  }
  if (!module.targets.every((target) => parentModule.targets.includes(target))) {
    fail(
      'invalid_parent_targets',
      `entry ${entry.entry_id} targets are outside parent ${parent.entry_id}`
    );
  }
}

function validateScope(scope: ScopeV2): void {
  const tenant = scope.tenant_id ?? null;
  const project = scope.project_id ?? null;
  const session = scope.session_id ?? null;
  const valid =
    (scope.kind === 'root' && tenant === null && project === null && session === null) ||
    (scope.kind === 'tenant' && tenant !== null && project === null && session === null) ||
    (scope.kind === 'project' && tenant !== null && project !== null && session === null) ||
    (scope.kind === 'session' && tenant !== null && project !== null && session !== null);
  if (!valid) fail('invalid_scope', `scope identifiers are inconsistent with ${scope.kind}`);
}

function scopeContains(parent: ScopeV2, child: ScopeV2): boolean {
  const rank: Record<ScopeKindV2, number> = {
    root: 0,
    tenant: 1,
    project: 2,
    session: 3,
  };
  return (
    rank[parent.kind] <= rank[child.kind] &&
    (parent.tenant_id == null || parent.tenant_id === child.tenant_id) &&
    (parent.project_id == null || parent.project_id === child.project_id) &&
    (parent.session_id == null || parent.session_id === child.session_id)
  );
}

function uniqueMap<T>(
  values: ReadonlyArray<T>,
  key: (value: T) => string,
  errorCode: string
): Map<string, T> {
  const result = new Map<string, T>();
  for (const value of values) {
    const identifier = key(value);
    if (result.has(identifier)) fail(errorCode, `duplicate identifier: ${identifier}`);
    result.set(identifier, value);
  }
  return result;
}

function objectValue(value: unknown, name: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    fail('schema_validation_failed', `${name} must be an object`);
  }
  return value as Record<string, unknown>;
}

function arrayValue(value: unknown, name: string): unknown[] {
  if (!Array.isArray(value)) fail('schema_validation_failed', `${name} must be an array`);
  return value;
}

function stringValue(value: unknown, name: string): string {
  if (typeof value !== 'string' || value.length === 0) {
    fail('schema_validation_failed', `${name} must be a non-empty string`);
  }
  return value;
}

function patternString(value: unknown, pattern: RegExp, name: string): string {
  const parsed = stringValue(value, name);
  if (!pattern.test(parsed)) fail('schema_validation_failed', `${name} has an invalid format`);
  return parsed;
}

function nullableString(value: unknown, name: string): string | null {
  return value === null ? null : stringValue(value, name);
}

function booleanValue(value: unknown, name: string): boolean {
  if (typeof value !== 'boolean') fail('schema_validation_failed', `${name} must be boolean`);
  return value;
}

function integerValue(value: unknown, name: string): number {
  if (!Number.isSafeInteger(value)) fail('schema_validation_failed', `${name} must be an integer`);
  return value as number;
}

function positiveInteger(value: unknown, name: string): number {
  const parsed = integerValue(value, name);
  if (parsed < 1) fail('schema_validation_failed', `${name} must be positive`);
  return parsed;
}

function nonNegativeInteger(value: unknown, name: string): number {
  const parsed = integerValue(value, name);
  if (parsed < 0) fail('schema_validation_failed', `${name} must be non-negative`);
  return parsed;
}

function uniqueStrings(value: unknown, name: string): string[] {
  const result = arrayValue(value, name).map((item, index) =>
    stringValue(item, `${name}[${index}]`)
  );
  if (new Set(result).size !== result.length) {
    fail('schema_validation_failed', `${name} must contain unique values`);
  }
  return result;
}

function stringRecord(value: unknown, name: string): Record<string, string> {
  return Object.fromEntries(
    Object.entries(objectValue(value, name)).map(([key, item]) => [
      key,
      stringValue(item, `${name}.${key}`),
    ])
  );
}

function enumValue<const T extends readonly string[]>(
  value: unknown,
  allowed: T,
  name: string
): T[number] {
  if (typeof value !== 'string' || !allowed.includes(value)) {
    fail('schema_validation_failed', `${name} has an unsupported value`);
  }
  return value as T[number];
}

function digestValue(value: unknown, name: string): string {
  const result = stringValue(value, name);
  if (!/^[0-9a-f]{64}$/.test(result)) fail('schema_validation_failed', `${name} is invalid`);
  return result;
}

function allowedKeys(object: Record<string, unknown>, allowed: readonly string[]): void {
  for (const key of Object.keys(object)) {
    if (!allowed.includes(key)) fail('schema_validation_failed', `unknown field: ${key}`);
  }
}

function requiredKeys(object: Record<string, unknown>, required: readonly string[]): void {
  for (const key of required) {
    if (!(key in object)) fail('schema_validation_failed', `missing field: ${key}`);
  }
}

function exactKeys(object: Record<string, unknown>, keys: readonly string[]): void {
  allowedKeys(object, keys);
  requiredKeys(object, keys);
}

function fail(code: string, message: string): never {
  throw new PluginProtocolV2Error(code, message);
}
