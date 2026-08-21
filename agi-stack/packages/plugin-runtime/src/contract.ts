import { canonicalJsonV2, digestV2 } from './canonical';
import { PluginProtocolV2Error } from './errors';
import type {
  DataPlaneTargetV2,
  EventContractV2,
  PluginContractV2,
  PluginManifestV2,
  PluginModuleV2,
  QuotaV2,
  ServiceProvidedV2,
  ServiceRequiredV2,
} from './generated';
import { parseContractSchemaV2 } from './schema';

const MODULE_REF = /^[a-z][a-z0-9+.-]*:\/\/.+$/;
const PLUGIN_ID = /^[a-z0-9][a-z0-9._-]{0,127}$/;
const SEMVER = /^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/;
const SERVICE = /^service:[a-z0-9][a-z0-9._:-]{0,255}$/;
const ALIAS = /^[a-z][a-z0-9_]{0,127}$/;
const EVENT = /^[a-z][a-z0-9._:-]{0,255}$/;

export function parsePluginManifestV2(value: unknown, index: number): PluginManifestV2 {
  const payload = objectValue(value, `manifests[${index}]`);
  exactKeys(payload, [
    'schema_version',
    'plugin_id',
    'version',
    'runtime',
    'trust',
    'modules',
    'permissions',
    'quotas',
  ]);
  if (payload.schema_version !== 2) {
    throw new PluginProtocolV2Error(
      'incompatible_schema_version',
      'manifest schema_version must be 2'
    );
  }
  const modules = arrayValue(payload.modules, 'modules').map(parsePluginModuleV2);
  if (modules.length === 0) schemaFail('modules must not be empty');
  unique(modules, (module) => module.module_ref, 'duplicate_module_ref');
  return {
    schema_version: 2,
    plugin_id: patternString(payload.plugin_id, PLUGIN_ID, 'plugin_id'),
    version: patternString(payload.version, SEMVER, 'version'),
    runtime: enumValue(
      payload.runtime,
      ['python-trusted', 'rust-native', 'wasm', 'mcp', 'subprocess', 'frontend'] as const,
      'runtime'
    ),
    trust: enumValue(
      payload.trust,
      ['builtin', 'signed', 'tenant-approved', 'untrusted'] as const,
      'trust'
    ),
    modules,
    permissions: uniqueStrings(payload.permissions, 'permissions'),
    quotas: parseQuota(payload.quotas),
  };
}

export function validateManifestContractsV2(manifests: ReadonlyArray<PluginManifestV2>): void {
  const signatures = new Map<string, string>();
  const owners = new Map<string, string>();
  for (const manifest of manifests) {
    for (const module of manifest.modules) {
      for (const declaration of [
        ...module.contract.events.emits,
        ...module.contract.events.handles,
      ]) {
        const signature = canonicalJsonV2({
          mode: declaration.mode,
          payload_schema: declaration.payload_schema,
          result_schema: declaration.result_schema,
        });
        const previous = signatures.get(declaration.event);
        if (previous !== undefined && previous !== signature) {
          throw new PluginProtocolV2Error(
            'event_contract_mismatch',
            `event ${declaration.event} differs between ${owners.get(declaration.event)} and ${module.module_ref}`
          );
        }
        signatures.set(declaration.event, signature);
        owners.set(declaration.event, module.module_ref);
      }
    }
  }
}

export async function validateManifestContractDigestsV2(
  manifests: ReadonlyArray<PluginManifestV2>
): Promise<void> {
  for (const manifest of manifests) {
    for (const module of manifest.modules) {
      const expected = `sha256:${await digestV2(module.contract)}`;
      if (module.contract_digest !== expected) {
        throw new PluginProtocolV2Error(
          'contract_digest_mismatch',
          `module ${module.module_ref} contract digest mismatch: expected ${expected}`
        );
      }
    }
  }
}

function parsePluginModuleV2(value: unknown, index: number): PluginModuleV2 {
  const payload = objectValue(value, `modules[${index}]`);
  exactKeys(payload, [
    'module_ref',
    'entrypoint',
    'artifact',
    'targets',
    'contract',
    'contract_digest',
  ]);
  const artifact = objectValue(payload.artifact, 'artifact');
  allowedKeys(artifact, ['digest', 'source', 'signature', 'provenance']);
  requiredKeys(artifact, ['digest', 'source']);
  return {
    module_ref: patternString(payload.module_ref, MODULE_REF, 'module_ref'),
    entrypoint: stringValue(payload.entrypoint, 'entrypoint'),
    targets: enumArray(
      payload.targets,
      ['python', 'rust-server', 'desktop-sidecar', 'web', 'desktop-renderer'] as const,
      'module.targets'
    ) as ReadonlyArray<DataPlaneTargetV2>,
    artifact: {
      digest: prefixedDigest(artifact.digest, 'artifact.digest'),
      source: stringValue(artifact.source, 'artifact.source'),
      ...(artifact.signature === undefined
        ? {}
        : {
            signature: nullableString(artifact.signature, 'artifact.signature'),
          }),
      ...(artifact.provenance === undefined
        ? {}
        : {
            provenance: nullableString(artifact.provenance, 'artifact.provenance'),
          }),
    },
    contract: parseContract(payload.contract),
    contract_digest: prefixedDigest(payload.contract_digest, 'contract_digest'),
  };
}

function parseContract(value: unknown): PluginContractV2 {
  const payload = objectValue(value, 'contract');
  exactKeys(payload, ['services', 'events', 'config_schema']);
  const services = objectValue(payload.services, 'contract.services');
  exactKeys(services, ['provides', 'requires']);
  const provides = arrayValue(services.provides, 'contract.services.provides').map(parseProvided);
  const requires = arrayValue(services.requires, 'contract.services.requires').map(parseRequired);
  unique(provides, (item) => `${item.service}\0${item.version}`, 'duplicate_service_provision');
  unique(requires, (item) => item.alias, 'duplicate_service_requirement');
  const events = objectValue(payload.events, 'contract.events');
  exactKeys(events, ['emits', 'handles']);
  return {
    services: { provides, requires },
    events: {
      emits: parseEvents(events.emits, 'contract.events.emits'),
      handles: parseEvents(events.handles, 'contract.events.handles'),
    },
    config_schema: parseContractSchemaV2(payload.config_schema, 'contract.config_schema', true),
  };
}

function parseProvided(value: unknown, index: number): ServiceProvidedV2 {
  const payload = objectValue(value, `provides[${index}]`);
  exactKeys(payload, ['service', 'version']);
  return {
    service: patternString(payload.service, SERVICE, 'service'),
    version: patternString(payload.version, SEMVER, 'service version'),
  };
}

function parseRequired(value: unknown, index: number): ServiceRequiredV2 {
  const payload = objectValue(value, `requires[${index}]`);
  exactKeys(payload, ['alias', 'service', 'version']);
  return {
    alias: patternString(payload.alias, ALIAS, 'service alias'),
    service: patternString(payload.service, SERVICE, 'service'),
    version: patternString(payload.version, SEMVER, 'service version'),
  };
}

function parseEvents(value: unknown, name: string): ReadonlyArray<EventContractV2> {
  const declarations = arrayValue(value, name).map((item, index) =>
    parseEvent(item, `${name}[${index}]`)
  );
  unique(declarations, (item) => item.event, 'duplicate_event_contract');
  return declarations;
}

function parseEvent(value: unknown, name: string): EventContractV2 {
  const payload = objectValue(value, name);
  exactKeys(payload, ['event', 'mode', 'payload_schema', 'result_schema']);
  return {
    event: patternString(payload.event, EVENT, `${name}.event`),
    mode: enumValue(payload.mode, ['emit', 'serial', 'bail', 'waterfall'] as const, `${name}.mode`),
    payload_schema: parseContractSchemaV2(payload.payload_schema, `${name}.payload_schema`),
    result_schema: parseContractSchemaV2(payload.result_schema, `${name}.result_schema`),
  };
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

function unique<T>(values: ReadonlyArray<T>, key: (value: T) => string, code: string): void {
  const seen = new Set<string>();
  for (const value of values) {
    const identifier = key(value);
    if (seen.has(identifier)) throw new PluginProtocolV2Error(code, `duplicate: ${identifier}`);
    seen.add(identifier);
  }
}

function objectValue(value: unknown, name: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    schemaFail(`${name} must be an object`);
  }
  return value as Record<string, unknown>;
}

function arrayValue(value: unknown, name: string): unknown[] {
  if (!Array.isArray(value)) schemaFail(`${name} must be an array`);
  return value;
}

function stringValue(value: unknown, name: string): string {
  if (typeof value !== 'string' || value.length === 0) {
    schemaFail(`${name} must be a non-empty string`);
  }
  return value;
}

function patternString(value: unknown, pattern: RegExp, name: string): string {
  const parsed = stringValue(value, name);
  if (!pattern.test(parsed)) schemaFail(`${name} has an invalid format`);
  return parsed;
}

function nullableString(value: unknown, name: string): string | null {
  return value === null ? null : stringValue(value, name);
}

function uniqueStrings(value: unknown, name: string): string[] {
  const result = arrayValue(value, name).map((item, index) =>
    stringValue(item, `${name}[${index}]`)
  );
  if (new Set(result).size !== result.length) schemaFail(`${name} must contain unique values`);
  return result;
}

function enumValue<const T extends readonly string[]>(
  value: unknown,
  allowed: T,
  name: string
): T[number] {
  if (typeof value !== 'string' || !allowed.includes(value)) {
    schemaFail(`${name} has an unsupported value`);
  }
  return value as T[number];
}

function enumArray<const T extends readonly string[]>(
  value: unknown,
  allowed: T,
  name: string
): T[number][] {
  const result = arrayValue(value, name).map((item, index) =>
    enumValue(item, allowed, `${name}[${index}]`)
  );
  if (result.length === 0 || new Set(result).size !== result.length) {
    schemaFail(`${name} must contain unique values`);
  }
  return result;
}

function prefixedDigest(value: unknown, name: string): string {
  const parsed = stringValue(value, name);
  if (!/^sha256:[0-9a-f]{64}$/.test(parsed)) schemaFail(`${name} is invalid`);
  return parsed;
}

function nonNegativeInteger(value: unknown, name: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) {
    schemaFail(`${name} must be non-negative`);
  }
  return value as number;
}

function allowedKeys(value: Record<string, unknown>, allowed: readonly string[]): void {
  for (const key of Object.keys(value))
    if (!allowed.includes(key)) schemaFail(`unknown field: ${key}`);
}

function requiredKeys(value: Record<string, unknown>, required: readonly string[]): void {
  for (const key of required) if (!(key in value)) schemaFail(`missing field: ${key}`);
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): void {
  allowedKeys(value, keys);
  requiredKeys(value, keys);
}

function schemaFail(message: string): never {
  throw new PluginProtocolV2Error('schema_validation_failed', message);
}
