import type { DesktopRuntimeConfig } from '../types';
import type {
  EvolutionRouteClient,
  EvolutionRouteConfig,
  EvolutionRouteOverview,
  EvolutionRouteScope,
} from '../features/settings-routes/evolutionRouteClient';
import {
  exactNativeRouteIdentifier,
  isNativeRouteRecord,
  NativeRouteClientError,
  requestNativeRouteJson,
  requireRuntimeAuthority,
  unavailableNativeRouteAction,
} from '../features/settings-routes/nativeRouteHttpClient';

const LOCAL_REASON = 'local_skill_evolution_authority_unavailable';
const ACTIONS = Object.freeze(['view', 'configure', 'run', 'apply-job', 'reject-job']);

export function createDesktopTenantEvolutionHttpProjectionV2(
  config: DesktopRuntimeConfig,
): EvolutionRouteClient {
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
      return Object.freeze({
        scope: current,
        authority: current.authority,
        availability: 'available',
        reasonCode: null,
        allowedActions: ACTIONS,
        itemCount: parsedOverview.skills.length,
        overview: parsedOverview,
        config: parseConfig(policy),
      });
    },
    async run(scope, signal) {
      const query = scopeQuery(scope);
      requireCloud(runtime);
      await requestNativeRouteJson(runtime, `/api/v1/skills/evolution/run?${query}`, {
        method: 'POST',
        signal,
      });
    },
    async updateConfig(scope, input, signal) {
      const query = scopeQuery(scope);
      requireCloud(runtime);
      return parseConfig(
        await requestNativeRouteJson(runtime, `/api/v1/skills/evolution/config?${query}`, {
          method: 'PUT',
          body: Object.freeze({ ...input }),
          signal,
        }),
      );
    },
    async reviewJob(scope, jobId, action, signal) {
      const query = scopeQuery(scope);
      requireCloud(runtime);
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

function requireCloud(config: DesktopRuntimeConfig): void {
  if (config.mode === 'local') unavailableNativeRouteAction(LOCAL_REASON);
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
    stats: freezeJsonRecord(value.stats),
    skills: Object.freeze(value.skills.map(freezeJsonRecord)),
    recent_sessions: Object.freeze(value.recent_sessions.map(freezeJsonRecord)),
    recent_jobs: Object.freeze(value.recent_jobs.map(freezeJsonRecord)),
    trigger: freezeJsonRecord(value.trigger),
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

function freezeJsonRecord(value: Record<string, unknown>): Readonly<Record<string, unknown>> {
  return freezeJson(value, 0) as Readonly<Record<string, unknown>>;
}

function freezeJson(value: unknown, depth: number): unknown {
  if (depth > 16) throw new NativeRouteClientError('skill_evolution_overview_contract_invalid', 502);
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) {
      throw new NativeRouteClientError('skill_evolution_overview_contract_invalid', 502);
    }
    return value;
  }
  if (Array.isArray(value)) {
    return Object.freeze(value.map((item) => freezeJson(item, depth + 1)));
  }
  if (!isNativeRouteRecord(value)) {
    throw new NativeRouteClientError('skill_evolution_overview_contract_invalid', 502);
  }
  const copy: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (key === '__proto__' || key === 'constructor' || key === 'prototype') {
      throw new NativeRouteClientError('skill_evolution_overview_contract_invalid', 502);
    }
    copy[key] = freezeJson(item, depth + 1);
  }
  return Object.freeze(copy);
}
