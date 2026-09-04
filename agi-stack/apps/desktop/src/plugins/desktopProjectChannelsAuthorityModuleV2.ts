import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type { ChannelsRouteClient } from '../features/settings-routes/channelsRouteClient';
import type {
  DesktopRuntimeConfig,
  ManagedChannelConfig,
  ManagedChannelPluginConfigSchema,
  ManagedChannelTestResult,
} from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import { createDesktopProjectChannelsHttpProjectionV2 } from './desktopProjectChannelsHttpProjectionV2';
import {
  prepareDesktopProjectChannelsCreateV2,
  prepareDesktopProjectChannelsItemV2,
  prepareDesktopProjectChannelsLoadV2,
  prepareDesktopProjectChannelsSchemaV2,
  prepareDesktopProjectChannelsUpdateV2,
  requireDesktopProjectChannelConfigV2,
  requireDesktopProjectChannelSchemaV2,
  requireDesktopProjectChannelsSnapshotV2,
  requireDesktopProjectChannelTestResultV2,
  type DesktopProjectChannelsAuthorityV2,
  type DesktopProjectChannelsCreateInputV2,
  type DesktopProjectChannelsItemInputV2,
  type DesktopProjectChannelsLoadInputV2,
  type DesktopProjectChannelsSchemaInputV2,
  type DesktopProjectChannelsSnapshotV2,
  type DesktopProjectChannelsUpdateInputV2,
} from './desktopProjectChannelsOperationContractV2';

export const DESKTOP_PROJECT_CHANNELS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-channels-authority';
export const DESKTOP_PROJECT_CHANNELS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-channels-authority';
export const DESKTOP_PROJECT_CHANNELS_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopProjectChannelsAuthorityServiceV2 {
  bindOperation(
    config: DesktopRuntimeConfig,
    scope: DesktopProjectChannelsLoadInputV2['scope'],
  ): DesktopProjectChannelsAuthorityV2;
}

export interface DesktopProjectChannelsOperationsV2 {
  loadProjectChannels(
    input: DesktopProjectChannelsLoadInputV2,
  ): Promise<DesktopProjectChannelsSnapshotV2>;
  getProjectChannelSchema(
    input: DesktopProjectChannelsSchemaInputV2,
  ): Promise<ManagedChannelPluginConfigSchema>;
  createProjectChannelConfig(
    input: DesktopProjectChannelsCreateInputV2,
  ): Promise<ManagedChannelConfig>;
  updateProjectChannelConfig(
    input: DesktopProjectChannelsUpdateInputV2,
  ): Promise<ManagedChannelConfig>;
  testProjectChannelConfig(
    input: DesktopProjectChannelsItemInputV2,
  ): Promise<ManagedChannelTestResult>;
  removeProjectChannelConfig(input: DesktopProjectChannelsItemInputV2): Promise<void>;
}

type Rejection =
  | Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }>
  | Readonly<{
      reasonCode: 'desktop_renderer_generation_actions_unavailable';
      runtimeCode?: undefined;
    }>;

export class DesktopProjectChannelsAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: Rejection['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: Rejection) {
    super(rejection.reasonCode);
    this.name = 'DesktopProjectChannelsAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopProjectChannelsAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_project_channels_authority_config_invalid',
      'desktop project channels authority requires desktop-api-fetch strategy',
    );
  }
  context.provide(
    DESKTOP_PROJECT_CHANNELS_AUTHORITY_SERVICE_V2,
    Object.freeze({
      bindOperation(configValue: DesktopRuntimeConfig) {
        return createDesktopProjectChannelsHttpProjectionV2(configValue);
      },
    }),
  );
}

export const desktopProjectChannelsAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PROJECT_CHANNELS_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopProjectChannelsAuthorityV2,
});

export function createDesktopProjectChannelsOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopProjectChannelsOperationsV2 {
  const operations: DesktopProjectChannelsOperationsV2 = {
    loadProjectChannels(input: DesktopProjectChannelsLoadInputV2) {
      const prepared = prepareDesktopProjectChannelsLoadV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopProjectChannelsSnapshotV2(
          await authority.load(prepared.scope, prepared.signal),
          prepared.scope,
        ),
      );
    },
    getProjectChannelSchema(input: DesktopProjectChannelsSchemaInputV2) {
      const prepared = prepareDesktopProjectChannelsSchemaV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopProjectChannelSchemaV2(
          await authority.schema(prepared.scope, prepared.channelType, prepared.signal),
          prepared.channelType,
        ),
      );
    },
    createProjectChannelConfig(input: DesktopProjectChannelsCreateInputV2) {
      const prepared = prepareDesktopProjectChannelsCreateV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopProjectChannelConfigV2(
          await authority.create(prepared.scope, prepared.input, prepared.signal),
          prepared.scope.projectId,
        ),
      );
    },
    updateProjectChannelConfig(input: DesktopProjectChannelsUpdateInputV2) {
      const prepared = prepareDesktopProjectChannelsUpdateV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopProjectChannelConfigV2(
          await authority.update(
            prepared.scope,
            prepared.configId,
            prepared.input,
            prepared.signal,
          ),
          prepared.scope.projectId,
        ),
      );
    },
    testProjectChannelConfig(input: DesktopProjectChannelsItemInputV2) {
      const prepared = prepareDesktopProjectChannelsItemV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopProjectChannelTestResultV2(
          await authority.test(prepared.scope, prepared.configId, prepared.signal),
        ),
      );
    },
    removeProjectChannelConfig(input: DesktopProjectChannelsItemInputV2) {
      const prepared = prepareDesktopProjectChannelsItemV2(input);
      return run(resolve, prepared, (authority) =>
        authority.remove(prepared.scope, prepared.configId, prepared.signal),
      );
    },
  };
  return Object.freeze(operations);
}

export function createDesktopProjectChannelsClientV2(
  operations: DesktopProjectChannelsOperationsV2,
  config: DesktopRuntimeConfig,
): ChannelsRouteClient {
  const frozen = Object.freeze({ ...config });
  return Object.freeze({
    observe: (scope, signal) =>
      operations.loadProjectChannels({
        config: frozen,
        scope,
        ...(signal === undefined ? {} : { signal }),
      }),
    getSchema: (scope, channelType, signal) =>
      operations.getProjectChannelSchema({
        config: frozen,
        scope,
        channelType,
        ...(signal === undefined ? {} : { signal }),
      }),
    create: (scope, input, signal) =>
      operations.createProjectChannelConfig({
        config: frozen,
        scope,
        input,
        ...(signal === undefined ? {} : { signal }),
      }),
    update: (scope, configId, input, signal) =>
      operations.updateProjectChannelConfig({
        config: frozen,
        scope,
        configId,
        input,
        ...(signal === undefined ? {} : { signal }),
      }),
    test: (scope, configId, signal) =>
      operations.testProjectChannelConfig({
        config: frozen,
        scope,
        configId,
        ...(signal === undefined ? {} : { signal }),
      }),
    remove: (scope, configId, signal) =>
      operations.removeProjectChannelConfig({
        config: frozen,
        scope,
        configId,
        ...(signal === undefined ? {} : { signal }),
      }),
  });
}

async function run<T>(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
  prepared: DesktopProjectChannelsLoadInputV2,
  operation: (authority: DesktopProjectChannelsAuthorityV2) => Promise<T>,
): Promise<T> {
  const actions = resolve();
  if (!actions) {
    throw new DesktopProjectChannelsAuthorityUnavailableErrorV2({
      reasonCode: 'desktop_renderer_generation_actions_unavailable',
    });
  }
  const admission =
    await actions.acquireServiceOperationLease<DesktopProjectChannelsAuthorityServiceV2>({
      service: DESKTOP_PROJECT_CHANNELS_AUTHORITY_SERVICE_V2,
      version: DESKTOP_PROJECT_CHANNELS_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.scope.tenantId,
        project_id: prepared.scope.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopProjectChannelsAuthorityUnavailableErrorV2(admission);
  }
  let failed = false;
  let active = true;
  try {
    return await admission.useService(async (candidate) => {
      assertActive(active);
      const service = requireService(candidate);
      const raw = service.bindOperation(prepared.config, prepared.scope);
      const result = await operation(wrapAuthority(raw, () => active));
      assertActive(active);
      return result;
    });
  } catch (error) {
    failed = true;
    throw error;
  } finally {
    active = false;
    try {
      await admission.release();
    } catch (error) {
      if (!failed) throw error;
    }
  }
}

function requireService(value: unknown): DesktopProjectChannelsAuthorityServiceV2 {
  if (
    !record(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidService();
  }
  return value as unknown as DesktopProjectChannelsAuthorityServiceV2;
}

function wrapAuthority(
  raw: unknown,
  active: () => boolean,
): DesktopProjectChannelsAuthorityV2 {
  const methods = ['load', 'schema', 'create', 'update', 'test', 'remove'] as const;
  if (
    !record(raw) ||
    Object.keys(raw).length !== methods.length ||
    methods.some((method) => typeof raw[method] !== 'function')
  ) {
    throw invalidService();
  }
  const authority = raw as unknown as DesktopProjectChannelsAuthorityV2;
  const wrapped: DesktopProjectChannelsAuthorityV2 = {
    load: (scope: DesktopProjectChannelsLoadInputV2['scope'], signal?: AbortSignal) =>
      invoke(active, authority.load, [scope, signal]),
    schema: (scope: DesktopProjectChannelsLoadInputV2['scope'], channelType: string, signal?: AbortSignal) =>
      invoke(active, authority.schema, [scope, channelType, signal]),
    create: (scope: DesktopProjectChannelsLoadInputV2['scope'], input: DesktopProjectChannelsCreateInputV2['input'], signal?: AbortSignal) =>
      invoke(active, authority.create, [scope, input, signal]),
    update: (scope: DesktopProjectChannelsLoadInputV2['scope'], configId: string, input: DesktopProjectChannelsUpdateInputV2['input'], signal?: AbortSignal) =>
      invoke(active, authority.update, [scope, configId, input, signal]),
    test: (scope: DesktopProjectChannelsLoadInputV2['scope'], configId: string, signal?: AbortSignal) =>
      invoke(active, authority.test, [scope, configId, signal]),
    remove: (scope: DesktopProjectChannelsLoadInputV2['scope'], configId: string, signal?: AbortSignal) =>
      invoke(active, authority.remove, [scope, configId, signal]),
  };
  return Object.freeze(wrapped);
}

async function invoke<TArgs extends readonly unknown[], TResult>(
  active: () => boolean,
  operation: (...args: TArgs) => TResult | Promise<TResult>,
  args: TArgs,
): Promise<TResult> {
  assertActive(active());
  const result = await operation(...args);
  assertActive(active());
  return result;
}

function assertActive(active: boolean): void {
  if (!active) {
    throw new RuntimeV2Error(
      'desktop_project_channels_operation_released',
      'desktop project channels operation released',
    );
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function invalidService(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_channels_service_invalid',
    'desktop project channels authority service invalid',
  );
}

function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_PROJECT_CHANNELS_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry) {
    throw new RuntimeV2Error(
      'desktop_project_channels_authority_catalog_missing',
      'desktop project channels authority absent from catalog',
    );
  }
  return entry.contract_digest;
}
