import type { ChannelsRouteScope } from '../features/settings-routes/channelsRouteClient';
import {
  exactNativeRouteIdentifier,
  isNativeRouteRecord,
  NativeRouteClientError,
  requestNativeRouteJson,
  requireRuntimeAuthority,
} from '../features/settings-routes/nativeRouteHttpClient';
import type {
  CreateManagedChannelConfigRequest,
  DesktopRuntimeConfig,
  ManagedChannelConfig,
  ManagedChannelPluginCatalogItem,
  ManagedChannelPluginConfigSchema,
  ManagedChannelTestResult,
  UpdateManagedChannelConfigRequest,
} from '../types';
import type {
  DesktopProjectChannelsAuthorityV2,
  DesktopProjectChannelsSnapshotV2,
} from './desktopProjectChannelsOperationContractV2';

export const DESKTOP_PROJECT_CHANNELS_LOCAL_REASON_V2 =
  'local_channel_runtime_not_applicable';

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

export function createDesktopProjectChannelsHttpProjectionV2(
  config: DesktopRuntimeConfig,
): DesktopProjectChannelsAuthorityV2 {
  const runtime = Object.freeze({ ...config });
  const authority: DesktopProjectChannelsAuthorityV2 = {
    async load(scope, signal): Promise<DesktopProjectChannelsSnapshotV2> {
      const current = requireScope(runtime, scope);
      const catalogPath =
        `/api/v1/channels/tenants/${encodeURIComponent(current.tenantId)}` +
        '/plugins/channel-catalog';
      if (runtime.mode === 'local') {
        return localUnavailable(() => requestNativeRouteJson(runtime, catalogPath, { signal }));
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
    async schema(scope, channelType, signal): Promise<ManagedChannelPluginConfigSchema> {
      const current = requireScope(runtime, scope);
      const type = exactNativeRouteIdentifier(channelType, 'project_channels_type_invalid');
      const path =
        `/api/v1/channels/tenants/${encodeURIComponent(current.tenantId)}` +
        `/plugins/channel-catalog/${encodeURIComponent(type)}/schema`;
      if (runtime.mode === 'local') {
        return localUnavailable(() => requestNativeRouteJson(runtime, path, { signal }));
      }
      return requireRecord<ManagedChannelPluginConfigSchema>(
        await requestNativeRouteJson(runtime, path, { signal }),
        'project_channels_schema_contract_invalid',
      );
    },
    async create(scope, input, signal): Promise<ManagedChannelConfig> {
      const current = requireScope(runtime, scope);
      const path = `/api/v1/channels/projects/${encodeURIComponent(current.projectId)}/configs`;
      if (runtime.mode === 'local') {
        return localUnavailable(() =>
          requestNativeRouteJson(runtime, path, { method: 'POST', body: input, signal }),
        );
      }
      return requireRecord<ManagedChannelConfig>(
        await requestNativeRouteJson(runtime, path, { method: 'POST', body: input, signal }),
        'project_channels_config_contract_invalid',
      );
    },
    async update(scope, configId, input, signal): Promise<ManagedChannelConfig> {
      requireScope(runtime, scope);
      const id = exactNativeRouteIdentifier(configId, 'project_channels_config_id_invalid');
      const path = `/api/v1/channels/configs/${encodeURIComponent(id)}`;
      if (runtime.mode === 'local') {
        return localUnavailable(() =>
          requestNativeRouteJson(runtime, path, { method: 'PUT', body: input, signal }),
        );
      }
      return requireRecord<ManagedChannelConfig>(
        await requestNativeRouteJson(runtime, path, { method: 'PUT', body: input, signal }),
        'project_channels_config_contract_invalid',
      );
    },
    async test(scope, configId, signal): Promise<ManagedChannelTestResult> {
      requireScope(runtime, scope);
      const id = exactNativeRouteIdentifier(configId, 'project_channels_config_id_invalid');
      const path = `/api/v1/channels/configs/${encodeURIComponent(id)}/test`;
      if (runtime.mode === 'local') {
        return localUnavailable(() =>
          requestNativeRouteJson(runtime, path, { method: 'POST', signal }),
        );
      }
      const result = await requestNativeRouteJson(runtime, path, { method: 'POST', signal });
      if (
        !isNativeRouteRecord(result) ||
        Object.keys(result).length !== 2 ||
        typeof result.success !== 'boolean' ||
        typeof result.message !== 'string'
      ) {
        throw new NativeRouteClientError('project_channels_test_contract_invalid', 502, result);
      }
      return Object.freeze({ success: result.success, message: result.message });
    },
    async remove(scope, configId, signal): Promise<void> {
      requireScope(runtime, scope);
      const id = exactNativeRouteIdentifier(configId, 'project_channels_config_id_invalid');
      const path = `/api/v1/channels/configs/${encodeURIComponent(id)}`;
      if (runtime.mode === 'local') {
        return localUnavailable(() =>
          requestNativeRouteJson(runtime, path, { method: 'DELETE', signal }),
        );
      }
      await requestNativeRouteJson(runtime, path, { method: 'DELETE', signal });
    },
  };
  return Object.freeze(authority);
}

function requireScope(
  config: DesktopRuntimeConfig,
  scope: ChannelsRouteScope,
): ChannelsRouteScope {
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

async function localUnavailable<T>(request: () => Promise<unknown>): Promise<T> {
  try {
    await request();
  } catch (error) {
    if (
      error instanceof NativeRouteClientError &&
      (error.status === 404 || error.status === 501)
    ) {
      throw new NativeRouteClientError(
        DESKTOP_PROJECT_CHANNELS_LOCAL_REASON_V2,
        error.status,
        error.payload,
      );
    }
    throw error;
  }
  throw new NativeRouteClientError('local_channel_runtime_authority_contract_invalid', 502);
}

function parseArray<T>(payload: unknown, keys: readonly string[]): readonly T[] {
  const direct = Array.isArray(payload) ? payload : null;
  const source = isNativeRouteRecord(payload) ? payload : null;
  const nested = keys.map((key) => source?.[key]).find(Array.isArray);
  const values = direct ?? nested;
  if (!values || values.some((item) => !isNativeRouteRecord(item))) {
    throw new NativeRouteClientError('project_channels_collection_contract_invalid', 502, payload);
  }
  return Object.freeze(values.map((item) => Object.freeze({ ...item }) as T));
}

function requireRecord<T>(payload: unknown, reasonCode: string): T {
  if (!isNativeRouteRecord(payload)) {
    throw new NativeRouteClientError(reasonCode, 502, payload);
  }
  return Object.freeze({ ...payload }) as T;
}
