import type {
  CreateManagedChannelConfigRequest,
  DesktopRuntimeConfig,
  ManagedChannelConfig,
  ManagedChannelPluginCatalogItem,
  ManagedChannelPluginConfigSchema,
  ManagedChannelTestResult,
  UpdateManagedChannelConfigRequest,
} from '../../types';
import {
  exactNativeRouteIdentifier,
  isNativeRouteRecord,
  NativeRouteClientError,
  requestNativeRouteJson,
  requireRuntimeAuthority,
} from './nativeRouteHttpClient';

export type ChannelsRouteScope = Readonly<{
  authority: DesktopRuntimeConfig['mode'];
  tenantId: string;
  projectId: string;
}>;

export type ChannelsRouteObservation = Readonly<{
  scope: ChannelsRouteScope;
  authority: DesktopRuntimeConfig['mode'];
  availability: 'available';
  reasonCode: null;
  allowedActions: readonly string[];
  itemCount: number;
  catalog: readonly ManagedChannelPluginCatalogItem[];
  configs: readonly ManagedChannelConfig[];
}>;

export type ChannelsRouteClient = Readonly<{
  observe(scope: ChannelsRouteScope, signal?: AbortSignal): Promise<ChannelsRouteObservation>;
  getSchema(
    scope: ChannelsRouteScope,
    channelType: string,
    signal?: AbortSignal,
  ): Promise<ManagedChannelPluginConfigSchema>;
  create(
    scope: ChannelsRouteScope,
    input: CreateManagedChannelConfigRequest,
    signal?: AbortSignal,
  ): Promise<ManagedChannelConfig>;
  update(
    scope: ChannelsRouteScope,
    configId: string,
    input: UpdateManagedChannelConfigRequest,
    signal?: AbortSignal,
  ): Promise<ManagedChannelConfig>;
  test(
    scope: ChannelsRouteScope,
    configId: string,
    signal?: AbortSignal,
  ): Promise<ManagedChannelTestResult>;
  remove(scope: ChannelsRouteScope, configId: string, signal?: AbortSignal): Promise<void>;
}>;

const ACTIONS = Object.freeze([
  'view',
  'view-channel-catalog',
  'view-channel-schema',
  'list-channel-configs',
  'create-channel-config',
  'update-channel-config',
  'delete-channel-config',
  'test-channel-config',
]);

export function createChannelsRouteClient(config: DesktopRuntimeConfig): ChannelsRouteClient {
  const runtime = Object.freeze({ ...config });
  return Object.freeze({
    async observe(scope, signal) {
      const current = requireScope(runtime, scope);
      const catalogPath =
        `/api/v1/channels/tenants/${encodeURIComponent(current.tenantId)}` +
        '/plugins/channel-catalog';
      if (runtime.mode === 'local') {
        await requestNativeRouteJson(runtime, catalogPath, { signal });
        throw new NativeRouteClientError('local_channel_runtime_authority_contract_invalid', 502);
      }
      const [catalogPayload, configsPayload] = await Promise.all([
        requestNativeRouteJson(runtime, catalogPath, { signal }),
        requestNativeRouteJson(
          runtime,
          `/api/v1/channels/projects/${encodeURIComponent(current.projectId)}/configs`,
          { signal },
        ),
      ]);
      const catalog = parseArray<ManagedChannelPluginCatalogItem>(catalogPayload, [
        'items',
        'data',
      ]);
      const configs = parseArray<ManagedChannelConfig>(configsPayload, ['items', 'data']);
      return Object.freeze({
        scope: current,
        authority: current.authority,
        availability: 'available',
        reasonCode: null,
        allowedActions: ACTIONS,
        itemCount: configs.length,
        catalog,
        configs,
      });
    },
    async getSchema(scope, channelType, signal) {
      const current = requireScope(runtime, scope);
      const type = exactNativeRouteIdentifier(channelType, 'project_channels_type_invalid');
      return requireRecord<ManagedChannelPluginConfigSchema>(
        await requestNativeRouteJson(
          runtime,
          `/api/v1/channels/tenants/${encodeURIComponent(current.tenantId)}/plugins/channel-catalog/${encodeURIComponent(type)}/schema`,
          { signal },
        ),
        'project_channels_schema_contract_invalid',
      );
    },
    async create(scope, input, signal) {
      const current = requireScope(runtime, scope);
      return requireRecord<ManagedChannelConfig>(
        await requestNativeRouteJson(
          runtime,
          `/api/v1/channels/projects/${encodeURIComponent(current.projectId)}/configs`,
          { method: 'POST', body: input, signal },
        ),
        'project_channels_config_contract_invalid',
      );
    },
    async update(scope, configId, input, signal) {
      requireScope(runtime, scope);
      const id = exactNativeRouteIdentifier(configId, 'project_channels_config_id_invalid');
      return requireRecord<ManagedChannelConfig>(
        await requestNativeRouteJson(
          runtime,
          `/api/v1/channels/configs/${encodeURIComponent(id)}`,
          { method: 'PUT', body: input, signal },
        ),
        'project_channels_config_contract_invalid',
      );
    },
    async test(scope, configId, signal) {
      requireScope(runtime, scope);
      const id = exactNativeRouteIdentifier(configId, 'project_channels_config_id_invalid');
      const result = await requestNativeRouteJson(
        runtime,
        `/api/v1/channels/configs/${encodeURIComponent(id)}/test`,
        { method: 'POST', signal },
      );
      if (
        !isNativeRouteRecord(result) ||
        typeof result.success !== 'boolean' ||
        typeof result.message !== 'string'
      ) {
        throw new NativeRouteClientError('project_channels_test_contract_invalid', 502, result);
      }
      return Object.freeze({
        success: result.success,
        message: result.message,
      });
    },
    async remove(scope, configId, signal) {
      requireScope(runtime, scope);
      const id = exactNativeRouteIdentifier(configId, 'project_channels_config_id_invalid');
      await requestNativeRouteJson(runtime, `/api/v1/channels/configs/${encodeURIComponent(id)}`, {
        method: 'DELETE',
        signal,
      });
    },
  });
}

function requireScope(config: DesktopRuntimeConfig, scope: ChannelsRouteScope): ChannelsRouteScope {
  requireRuntimeAuthority(config, scope.authority, 'project_channels_runtime_scope_mismatch');
  const tenantId = exactNativeRouteIdentifier(
    scope.tenantId,
    'project_channels_tenant_scope_invalid',
  );
  const projectId = exactNativeRouteIdentifier(
    scope.projectId,
    'project_channels_project_scope_invalid',
  );
  if (tenantId !== config.tenantId || projectId !== config.projectId) {
    throw new NativeRouteClientError('project_channels_runtime_scope_mismatch', 409);
  }
  return Object.freeze({ authority: scope.authority, tenantId, projectId });
}

function parseArray<T>(payload: unknown, keys: readonly string[]): readonly T[] {
  const direct = Array.isArray(payload) ? payload : null;
  const record = isNativeRouteRecord(payload) ? payload : null;
  const nested = keys.map((key) => record?.[key]).find(Array.isArray);
  const values = direct ?? nested;
  if (!values || values.some((value) => !isNativeRouteRecord(value))) {
    throw new NativeRouteClientError('project_channels_collection_contract_invalid', 502, payload);
  }
  return Object.freeze(values.map((value) => Object.freeze({ ...value }) as T));
}

function requireRecord<T>(payload: unknown, reasonCode: string): T {
  if (!isNativeRouteRecord(payload)) {
    throw new NativeRouteClientError(reasonCode, 502, payload);
  }
  return Object.freeze({ ...payload }) as T;
}
