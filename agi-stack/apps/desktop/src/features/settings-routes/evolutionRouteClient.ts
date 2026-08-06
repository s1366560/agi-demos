import type { DesktopRuntimeConfig } from '../../types';
import {
  exactNativeRouteIdentifier,
  isNativeRouteRecord,
  NativeRouteClientError,
  requestNativeRouteJson,
  requireRuntimeAuthority,
} from './nativeRouteHttpClient';

export type EvolutionRouteScope = Readonly<{
  authority: DesktopRuntimeConfig['mode'];
  tenantId: string;
}>;

export type EvolutionRouteConfig = Readonly<{
  enabled: boolean;
  min_sessions_per_skill: number;
  scoring_min_sessions_per_skill: number;
  min_avg_score: number;
  max_sessions_per_batch: number;
  evolution_interval_minutes: number;
  publish_mode: string;
  auto_apply: boolean;
}>;

export type EvolutionRouteOverview = Readonly<{
  stats: Readonly<Record<string, unknown>>;
  skills: readonly Readonly<Record<string, unknown>>[];
  recent_sessions: readonly Readonly<Record<string, unknown>>[];
  recent_jobs: readonly Readonly<Record<string, unknown>>[];
  trigger: Readonly<Record<string, unknown>>;
}>;

export type EvolutionRouteObservation = Readonly<{
  scope: EvolutionRouteScope;
  authority: DesktopRuntimeConfig['mode'];
  availability: 'available';
  reasonCode: null;
  allowedActions: readonly string[];
  itemCount: number;
  overview: EvolutionRouteOverview;
  config: EvolutionRouteConfig;
}>;

export type EvolutionRouteClient = Readonly<{
  observe(scope: EvolutionRouteScope, signal?: AbortSignal): Promise<EvolutionRouteObservation>;
  run(scope: EvolutionRouteScope, signal?: AbortSignal): Promise<void>;
  updateConfig(
    scope: EvolutionRouteScope,
    input: Partial<EvolutionRouteConfig>,
    signal?: AbortSignal,
  ): Promise<EvolutionRouteConfig>;
  reviewJob(
    scope: EvolutionRouteScope,
    jobId: string,
    action: 'apply' | 'reject',
    signal?: AbortSignal,
  ): Promise<void>;
}>;

const ACTIONS = Object.freeze(['view', 'configure', 'run', 'apply-job', 'reject-job']);

export function createEvolutionRouteClient(config: DesktopRuntimeConfig): EvolutionRouteClient {
  const runtime = Object.freeze({ ...config });
  const scopeQuery = (scope: EvolutionRouteScope): string => {
    const current = requireScope(runtime, scope);
    return new URLSearchParams({ tenant_id: current.tenantId }).toString();
  };
  return Object.freeze({
    async observe(scope, signal) {
      const query = scopeQuery(scope);
      if (runtime.mode === 'local') {
        await requestNativeRouteJson(runtime, `/api/v1/skills/evolution/overview?${query}`, {
          signal,
        });
        throw new NativeRouteClientError('local_skill_evolution_authority_contract_invalid', 502);
      }
      const [overview, policy] = await Promise.all([
        requestNativeRouteJson(runtime, `/api/v1/skills/evolution/overview?${query}`, { signal }),
        requestNativeRouteJson(runtime, `/api/v1/skills/evolution/config?${query}`, { signal }),
      ]);
      const current = requireScope(runtime, scope);
      const parsedOverview = parseOverview(overview);
      const parsedConfig = parseConfig(policy);
      return Object.freeze({
        scope: current,
        authority: current.authority,
        availability: 'available',
        reasonCode: null,
        allowedActions: ACTIONS,
        itemCount: parsedOverview.skills.length,
        overview: parsedOverview,
        config: parsedConfig,
      });
    },
    async run(scope, signal) {
      const query = scopeQuery(scope);
      await requestNativeRouteJson(runtime, `/api/v1/skills/evolution/run?${query}`, {
        method: 'POST',
        signal,
      });
    },
    async updateConfig(scope, input, signal) {
      const query = scopeQuery(scope);
      return parseConfig(
        await requestNativeRouteJson(runtime, `/api/v1/skills/evolution/config?${query}`, {
          method: 'PUT',
          body: input,
          signal,
        }),
      );
    },
    async reviewJob(scope, jobId, action, signal) {
      const query = scopeQuery(scope);
      const id = encodeURIComponent(
        exactNativeRouteIdentifier(jobId, 'skill_evolution_job_id_invalid'),
      );
      await requestNativeRouteJson(
        runtime,
        `/api/v1/skills/evolution/jobs/${id}/${action}?${query}`,
        { method: 'POST', signal },
      );
    },
  });
}

function requireScope(
  config: DesktopRuntimeConfig,
  scope: EvolutionRouteScope,
): EvolutionRouteScope {
  requireRuntimeAuthority(config, scope.authority, 'skill_evolution_runtime_scope_mismatch');
  const tenantId = exactNativeRouteIdentifier(
    scope.tenantId,
    'skill_evolution_tenant_scope_invalid',
  );
  if (tenantId !== config.tenantId) {
    throw new NativeRouteClientError('skill_evolution_runtime_scope_mismatch', 409);
  }
  return Object.freeze({ authority: scope.authority, tenantId });
}

function parseOverview(value: unknown): EvolutionRouteOverview {
  if (
    !isNativeRouteRecord(value) ||
    !isNativeRouteRecord(value.stats) ||
    !Array.isArray(value.skills) ||
    !Array.isArray(value.recent_sessions) ||
    !Array.isArray(value.recent_jobs) ||
    !isNativeRouteRecord(value.trigger) ||
    value.skills.some((item) => !isNativeRouteRecord(item)) ||
    value.recent_sessions.some((item) => !isNativeRouteRecord(item)) ||
    value.recent_jobs.some((item) => !isNativeRouteRecord(item))
  ) {
    throw new NativeRouteClientError('skill_evolution_overview_contract_invalid', 502, value);
  }
  return Object.freeze({
    stats: Object.freeze({ ...value.stats }),
    skills: Object.freeze(value.skills.map((item) => Object.freeze({ ...item }))),
    recent_sessions: Object.freeze(value.recent_sessions.map((item) => Object.freeze({ ...item }))),
    recent_jobs: Object.freeze(value.recent_jobs.map((item) => Object.freeze({ ...item }))),
    trigger: Object.freeze({ ...value.trigger }),
  });
}

function parseConfig(value: unknown): EvolutionRouteConfig {
  if (!isNativeRouteRecord(value)) {
    throw new NativeRouteClientError('skill_evolution_config_contract_invalid', 502, value);
  }
  const numericKeys = [
    'min_sessions_per_skill',
    'scoring_min_sessions_per_skill',
    'min_avg_score',
    'max_sessions_per_batch',
    'evolution_interval_minutes',
  ] as const;
  if (
    typeof value.enabled !== 'boolean' ||
    typeof value.auto_apply !== 'boolean' ||
    typeof value.publish_mode !== 'string' ||
    numericKeys.some((key) => typeof value[key] !== 'number' || !Number.isFinite(value[key]))
  ) {
    throw new NativeRouteClientError('skill_evolution_config_contract_invalid', 502, value);
  }
  return Object.freeze({
    enabled: value.enabled,
    min_sessions_per_skill: value.min_sessions_per_skill as number,
    scoring_min_sessions_per_skill: value.scoring_min_sessions_per_skill as number,
    min_avg_score: value.min_avg_score as number,
    max_sessions_per_batch: value.max_sessions_per_batch as number,
    evolution_interval_minutes: value.evolution_interval_minutes as number,
    publish_mode: value.publish_mode,
    auto_apply: value.auto_apply,
  });
}
