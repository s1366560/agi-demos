import type { DesktopRuntimeConfig } from '../types';
import type { LocalPluginTransport } from './localPluginClient';

export interface PluginInstanceScopeV2 {
  readonly kind: 'tenant' | 'project';
  readonly tenant_id: string;
  readonly project_id: string | null;
  readonly session_id: null;
}

export interface PluginInstanceReplacementV2 {
  readonly plugin_id: string;
  readonly module_ref: string;
}

export interface PluginInstanceV2 {
  readonly entry_id: string;
  readonly plugin_id: string;
  readonly display_name: string;
  readonly module_ref: string;
  readonly enabled: boolean;
  readonly config: Readonly<Record<string, unknown>>;
  readonly config_schema: Readonly<Record<string, unknown>>;
  readonly editable: boolean;
  readonly config_editable: boolean;
  readonly reason_code: string | null;
  readonly inherited_from: PluginInstanceScopeV2 | null;
  readonly replacement_candidates: readonly PluginInstanceReplacementV2[];
  readonly state: {
    readonly status: 'active' | 'disabled' | 'applying' | 'failed';
    readonly reason_code: string | null;
  };
}

export interface PluginInstancesResponseV2 {
  readonly scope: PluginInstanceScopeV2;
  readonly revision: number;
  readonly publication: {
    readonly status: 'unpublished' | 'reconciling' | 'ready' | 'degraded';
    readonly publication_id: string | null;
    readonly generation: number | null;
  };
  readonly instances: readonly PluginInstanceV2[];
}

export interface PluginInstanceChangeV2 {
  readonly entry_id: string;
  readonly enabled?: boolean;
  readonly config?: Readonly<Record<string, unknown>>;
  readonly replacement?: PluginInstanceReplacementV2;
}

export interface PluginInstanceRequestScopeV2 {
  readonly tenant_id: string;
  readonly project_id?: string | null;
}

export interface PluginInstanceClientV2 {
  list(signal?: AbortSignal): Promise<PluginInstancesResponseV2>;
  apply(
    expectedRevision: number,
    changes: readonly PluginInstanceChangeV2[],
    signal?: AbortSignal,
  ): Promise<PluginInstancesResponseV2>;
}

export function createPluginInstanceClientV2(
  config: DesktopRuntimeConfig,
  transport: LocalPluginTransport,
): PluginInstanceClientV2 {
  const root =
    config.mode === 'local'
      ? '/api/v1/local-plugins/v2/instances'
      : '/api/v1/platform-plugins/v2/instances';
  const scope = {
    tenant_id: config.tenantId,
    ...(config.projectId ? { project_id: config.projectId } : {}),
  };
  const check = (value: unknown): PluginInstancesResponseV2 => {
    const result = value as PluginInstancesResponseV2;
    if (
      !result ||
      !Number.isSafeInteger(result.revision) ||
      result.revision < 0 ||
      !Array.isArray(result.instances) ||
      result.scope?.tenant_id !== config.tenantId ||
      (result.scope.project_id ?? '') !== config.projectId
    )
      throw new Error('plugin_instances_response_invalid');
    return result;
  };
  return Object.freeze({
    list: async (signal?: AbortSignal) =>
      check(await transport(`${root}?${new URLSearchParams(scope)}`, { signal })),
    apply: async (
      expectedRevision: number,
      changes: readonly PluginInstanceChangeV2[],
      signal?: AbortSignal,
    ) =>
      check(
        await transport(`${root}/apply`, {
          method: 'POST',
          body: { ...scope, expected_revision: expectedRevision, changes },
          signal,
        }),
      ),
  });
}
