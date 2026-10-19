import { kernelHttpClient } from './client/kernelHttpClient';

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

export const pluginInstanceServiceV2 = {
  list(
    scope: PluginInstanceRequestScopeV2,
    signal?: AbortSignal
  ): Promise<PluginInstancesResponseV2> {
    return kernelHttpClient.get('/platform-plugins/v2/instances', {
      params: scope,
      ...(signal ? { signal } : {}),
    });
  },
  apply(
    scope: PluginInstanceRequestScopeV2,
    expectedRevision: number,
    changes: readonly PluginInstanceChangeV2[]
  ): Promise<PluginInstancesResponseV2> {
    return kernelHttpClient.post('/platform-plugins/v2/instances/apply', {
      ...scope,
      expected_revision: expectedRevision,
      changes,
    });
  },
};
