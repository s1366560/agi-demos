import type { DesktopRuntimeConfig } from '../../types';

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
