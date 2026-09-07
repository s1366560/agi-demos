import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  EvolutionRouteConfig,
  EvolutionRouteObservation,
  EvolutionRouteScope,
} from '../features/settings-routes/evolutionRouteClient';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopTenantEvolutionInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: EvolutionRouteScope;
  signal?: AbortSignal;
}>;
export type DesktopTenantEvolutionUpdateInputV2 = DesktopTenantEvolutionInputV2 &
  Readonly<{ update: Partial<EvolutionRouteConfig> }>;
export type DesktopTenantEvolutionReviewInputV2 = DesktopTenantEvolutionInputV2 &
  Readonly<{ jobId: string; action: 'apply' | 'reject' }>;

const CONFIG_KEYS = Object.freeze([
  'apiBaseUrl',
  'deviceAuthorizationBaseUrl',
  'apiKey',
  'localApiToken',
  'tenantId',
  'projectId',
  'workspaceId',
  'mode',
  'workspaceRoot',
]);
const EVOLUTION_CONFIG_KEYS = Object.freeze([
  'enabled',
  'min_sessions_per_skill',
  'scoring_min_sessions_per_skill',
  'min_avg_score',
  'max_sessions_per_batch',
  'evolution_interval_minutes',
  'publish_mode',
  'auto_apply',
]);
const OBSERVATION_KEYS = Object.freeze([
  'scope',
  'authority',
  'availability',
  'reasonCode',
  'allowedActions',
  'itemCount',
  'overview',
  'config',
]);
const OVERVIEW_KEYS = Object.freeze([
  'stats',
  'skills',
  'recent_sessions',
  'recent_jobs',
  'trigger',
]);
const ACTIONS = Object.freeze(['view', 'configure', 'run', 'apply-job', 'reject-job']);

export function prepareTenantEvolutionInputV2(
  input: DesktopTenantEvolutionInputV2,
): DesktopTenantEvolutionInputV2 {
  return Object.freeze(prepareCommon(input));
}

export function prepareTenantEvolutionUpdateV2(
  input: DesktopTenantEvolutionUpdateInputV2,
): DesktopTenantEvolutionUpdateInputV2 {
  const common = prepareCommon(input);
  if (
    !record(input.update) ||
    Object.keys(input.update).length === 0 ||
    Object.keys(input.update).some((key) => !EVOLUTION_CONFIG_KEYS.includes(key))
  ) {
    throw invalidInput();
  }
  return Object.freeze({ ...common, update: freezeEvolutionUpdate(input.update) });
}

export function prepareTenantEvolutionReviewV2(
  input: DesktopTenantEvolutionReviewInputV2,
): DesktopTenantEvolutionReviewInputV2 {
  const common = prepareCommon(input);
  if (input.action !== 'apply' && input.action !== 'reject') throw invalidInput();
  return Object.freeze({ ...common, jobId: identifier(input.jobId), action: input.action });
}

export function freezeTenantEvolutionConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (
    !record(config) ||
    Object.keys(config).length !== CONFIG_KEYS.length ||
    CONFIG_KEYS.some((key) => !Object.hasOwn(config, key)) ||
    (config.mode !== 'cloud' && config.mode !== 'local')
  ) {
    throw invalidInput();
  }
  for (const key of CONFIG_KEYS) {
    if (key !== 'mode' && typeof config[key as keyof DesktopRuntimeConfig] !== 'string') {
      throw invalidInput();
    }
  }
  identifier(config.tenantId);
  return Object.freeze({ ...config });
}

export function requireTenantEvolutionObservationV2(
  value: unknown,
  scope: EvolutionRouteScope,
): EvolutionRouteObservation {
  if (
    !exactRecord(value, OBSERVATION_KEYS) ||
    !exactRecord(value.scope, ['authority', 'tenantId']) ||
    value.scope.authority !== scope.authority ||
    value.scope.tenantId !== scope.tenantId ||
    value.authority !== scope.authority ||
    value.availability !== 'available' ||
    value.reasonCode !== null ||
    !sameStringArray(value.allowedActions, ACTIONS) ||
    !Number.isSafeInteger(value.itemCount) ||
    Number(value.itemCount) < 0 ||
    !exactRecord(value.overview, OVERVIEW_KEYS) ||
    !record(value.overview.stats) ||
    !record(value.overview.trigger) ||
    !recordArray(value.overview.skills) ||
    !recordArray(value.overview.recent_sessions) ||
    !recordArray(value.overview.recent_jobs) ||
    value.itemCount !== value.overview.skills.length
  ) {
    throw invalidResponse();
  }
  requireTenantEvolutionConfigV2(value.config);
  return value as unknown as EvolutionRouteObservation;
}

export function requireTenantEvolutionConfigV2(value: unknown): EvolutionRouteConfig {
  if (
    !exactRecord(value, EVOLUTION_CONFIG_KEYS) ||
    typeof value.enabled !== 'boolean' ||
    typeof value.auto_apply !== 'boolean' ||
    typeof value.publish_mode !== 'string' ||
    !value.publish_mode ||
    value.publish_mode !== value.publish_mode.trim() ||
    !finite(value.min_sessions_per_skill) ||
    !finite(value.scoring_min_sessions_per_skill) ||
    !finite(value.min_avg_score) ||
    !finite(value.max_sessions_per_batch) ||
    !finite(value.evolution_interval_minutes)
  ) {
    throw invalidResponse();
  }
  return value as unknown as EvolutionRouteConfig;
}

function prepareCommon(input: DesktopTenantEvolutionInputV2) {
  if (!record(input)) throw invalidInput();
  const config = freezeTenantEvolutionConfigV2(input.config);
  if (
    !exactRecord(input.scope, ['authority', 'tenantId']) ||
    input.scope.authority !== config.mode ||
    identifier(input.scope.tenantId) !== config.tenantId
  ) {
    throw invalidInput();
  }
  if (
    input.signal !== undefined &&
    (!record(input.signal) ||
      typeof input.signal.aborted !== 'boolean' ||
      typeof input.signal.addEventListener !== 'function')
  ) {
    throw invalidInput();
  }
  return {
    config,
    scope: Object.freeze({ authority: input.scope.authority, tenantId: input.scope.tenantId }),
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  };
}

function freezeEvolutionUpdate(
  value: Partial<EvolutionRouteConfig>,
): Partial<EvolutionRouteConfig> {
  const copy: Partial<EvolutionRouteConfig> = {};
  for (const key of Object.keys(value) as (keyof EvolutionRouteConfig)[]) {
    const item = value[key];
    if (key === 'enabled' || key === 'auto_apply') {
      if (typeof item !== 'boolean') throw invalidInput();
    } else if (key === 'publish_mode') {
      if (typeof item !== 'string' || !item || item !== item.trim()) throw invalidInput();
    } else if (!finite(item)) {
      throw invalidInput();
    }
    Object.assign(copy, { [key]: item });
  }
  return Object.freeze(copy);
}

function sameStringArray(value: unknown, expected: readonly string[]): boolean {
  return (
    Array.isArray(value) &&
    value.length === expected.length &&
    value.every((item, index) => item === expected[index])
  );
}

function recordArray(value: unknown): value is readonly Readonly<Record<string, unknown>>[] {
  return Array.isArray(value) && value.every(record);
}

function exactRecord(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  return record(value) && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function identifier(value: unknown): string {
  if (typeof value !== 'string' || !value || value !== value.trim()) throw invalidInput();
  return value;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalidInput(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_evolution_operation_input_invalid',
    'desktop tenant evolution operation input invalid',
  );
}

function invalidResponse(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_evolution_operation_response_invalid',
    'desktop tenant evolution operation response invalid',
  );
}
