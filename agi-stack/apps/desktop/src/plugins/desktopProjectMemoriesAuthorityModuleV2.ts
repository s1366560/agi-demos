import {
  prepareNativeKnowledgeCloudConnection,
  requireNativeKnowledgeCloudConnectionResponse,
  type NativeKnowledgeCloudConnectionAuthority,
  type NativeKnowledgeCloudConnectionClient,
  type NativeKnowledgeCloudConnectionCommand,
  type NativeKnowledgeCloudConnectionResponse,
  type NativeKnowledgeCloudConnectionOptions,
} from '../features/project-knowledge/nativeKnowledgeCloudConnectionClient';
import type { DesktopProjectMemoriesConnectionInputV2 } from './desktopProjectMemoriesOperationContractV2';
import type {
  DesktopNativeKnowledgeProcessingHttpV2,
  NativeKnowledgeProcessingCapabilityGetter,
} from './desktopNativeKnowledgeProcessingHttpV2';
import type {
  NativeKnowledgeProcessingQuery,
  NativeKnowledgeProcessingCommand,
  NativeKnowledgeProcessingResponse,
  NativeKnowledgeProcessingCommandResponse,
  NativeKnowledgeObservedOptions,
} from '../features/project-knowledge/nativeKnowledgeContracts';
import type {
  DesktopProjectMemoriesProcessingQueryInputV2,
  DesktopProjectMemoriesProcessingCommandInputV2,
} from './desktopProjectMemoriesOperationContractV2';
import { createRevocableKnowledgeProcessingV2 } from './desktopProjectMemoriesProcessingBridgeV2';
export {
  createDesktopNativeKnowledgeProcessingClientV2,
  createDesktopNativeKnowledgeProcessingCommandClientV2,
} from './desktopProjectMemoriesProcessingBridgeV2';
import type {
  CloudMemoryClient,
  CloudMemoryCommand,
  CloudMemoryOptions,
  CloudMemoryResponse,
} from '../features/project-knowledge/cloudMemoryClient';
import {
  prepareCloudMemoryCommand,
  prepareCloudMemoryOptions,
} from '../features/project-knowledge/cloudMemoryValidation';
import { requireCloudMemoryResponse } from '../features/project-knowledge/cloudMemoryResponse';
import type { DesktopProjectMemoriesCloudOperationInputV2 } from './desktopProjectMemoriesOperationContractV2';
import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  ProjectMemoriesClient,
  ProjectMemoriesSnapshot,
  ProjectMemoriesPageOptions,
} from '../features/project-knowledge/projectMemoriesClient';
import type { ProjectKnowledgeScope } from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopRuntimeConfig } from '../types';
import type {
  NativeKnowledgeClient,
  NativeKnowledgeCommand,
  NativeKnowledgeResponse,
  NativeKnowledgeSyncAuthority,
  NativeKnowledgeSyncOptions,
  NativeKnowledgeScope,
  NativeKnowledgeScopeObservationOptions,
} from '../features/project-knowledge/nativeKnowledgeContracts';
import {
  prepareNativeKnowledgeCommand,
  requireNativeKnowledgeCommandOptions,
  requireNativeKnowledgeResponse,
  requireNativeKnowledgeScope,
} from '../features/project-knowledge/nativeKnowledgeValidation';
import { prepareNativeKnowledgeScopeObservationOptions } from '../features/project-knowledge/nativeKnowledgeScopeObservation';
import { projectKnowledgeError } from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopProjectMemoriesObserveScopeInputV2 } from './desktopProjectMemoriesOperationContractV2';
import { createDesktopProjectMemoriesHttpAuthorityV2 } from './desktopProjectMemoriesHttpProjectionV2';
import {
  prepareDesktopProjectMemoriesAuthorityOperationV2,
  requireDesktopProjectMemoriesSnapshotV2,
  normalizeDesktopProjectMemoriesPageV2,
  type DesktopProjectMemoriesAuthorityOperationInputV2,
  type DesktopProjectMemoriesLoadOperationInputV2,
  type DesktopProjectMemoriesSyncOperationInputV2,
  type PreparedDesktopProjectMemoriesAuthorityOperationV2,
} from './desktopProjectMemoriesOperationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export type {
  DesktopProjectMemoriesAuthorityOperationInputV2,
  DesktopProjectMemoriesLoadOperationInputV2,
  DesktopProjectMemoriesSyncOperationInputV2,
} from './desktopProjectMemoriesOperationContractV2';

export const DESKTOP_PROJECT_MEMORIES_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-memories-authority';
export const DESKTOP_PROJECT_MEMORIES_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-memories-authority';
export const DESKTOP_PROJECT_MEMORIES_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopProjectMemoriesAuthorityV2
  extends
    NativeKnowledgeSyncAuthority,
    Partial<DesktopNativeKnowledgeProcessingHttpV2>,
    Partial<NativeKnowledgeCloudConnectionAuthority> {
  readonly executeCloudMemory?: <C extends CloudMemoryCommand>(
    command: C,
    options: CloudMemoryOptions,
  ) => Promise<CloudMemoryResponse<C>>;
  readonly load: (
    signal?: AbortSignal,
    options?: ProjectMemoriesPageOptions,
  ) => Promise<ProjectMemoriesSnapshot>;
}

export interface DesktopProjectMemoriesAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: ProjectKnowledgeScope,
    getCapability?: NativeKnowledgeProcessingCapabilityGetter,
  ) => DesktopProjectMemoriesAuthorityV2;
}

export interface DesktopProjectMemoriesOperationsV2 {
  readonly executeKnowledgeConnection: <C extends NativeKnowledgeCloudConnectionCommand>(
    input: DesktopProjectMemoriesConnectionInputV2<C>,
  ) => Promise<NativeKnowledgeCloudConnectionResponse<C>>;
  readonly observeNativeKnowledgeScope: (
    input: DesktopProjectMemoriesObserveScopeInputV2,
  ) => Promise<NativeKnowledgeScope>;
  readonly queryKnowledgeProcessing: <Q extends NativeKnowledgeProcessingQuery>(
    input: DesktopProjectMemoriesProcessingQueryInputV2<Q>,
  ) => Promise<NativeKnowledgeProcessingResponse<Q>>;
  readonly executeKnowledgeProcessing: <C extends NativeKnowledgeProcessingCommand>(
    input: DesktopProjectMemoriesProcessingCommandInputV2<C>,
  ) => Promise<NativeKnowledgeProcessingCommandResponse<C>>;
  readonly executeCloudMemory: <C extends CloudMemoryCommand>(
    input: DesktopProjectMemoriesCloudOperationInputV2<C>,
  ) => Promise<CloudMemoryResponse<C>>;
  readonly executeKnowledgeSync: <C extends NativeKnowledgeCommand>(
    input: DesktopProjectMemoriesSyncOperationInputV2<C>,
  ) => Promise<NativeKnowledgeResponse<C>>;
  readonly loadProjectMemories: (
    input: DesktopProjectMemoriesLoadOperationInputV2,
  ) => Promise<ProjectMemoriesSnapshot>;
}

type ServiceAdmissionRejectionV2 = Extract<
  DesktopRendererServiceOperationLeaseAdmissionV2<never>,
  { status: 'rejected' }
>;
type GenerationActionsUnavailableV2 = Readonly<{
  reasonCode: 'desktop_renderer_generation_actions_unavailable';
  runtimeCode?: undefined;
}>;
type AuthorityAdmissionRejectionV2 = ServiceAdmissionRejectionV2 | GenerationActionsUnavailableV2;

const AUTHORITY_KEYS_V2 = new Set([
  'observeScope',
  'executeConnection',
  'load',
  'executeSync',
  'executeCloudMemory',
  'queryProcessing',
  'executeProcessing',
]);

export class DesktopProjectMemoriesAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopProjectMemoriesAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopProjectMemoriesAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_project_memories_authority_config_invalid',
      'desktop project memories authority requires desktop-api-fetch strategy',
    );
  }
  const service: DesktopProjectMemoriesAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopProjectMemoriesHttpAuthorityV2,
  });
  context.provide(DESKTOP_PROJECT_MEMORIES_AUTHORITY_SERVICE_V2, service);
}

export const desktopProjectMemoriesAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PROJECT_MEMORIES_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopProjectMemoriesAuthorityV2,
});

export function createDesktopProjectMemoriesOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
  getCapability?: NativeKnowledgeProcessingCapabilityGetter,
): DesktopProjectMemoriesOperationsV2 {
  return Object.freeze({
    executeKnowledgeConnection<C extends NativeKnowledgeCloudConnectionCommand>(
      input: DesktopProjectMemoriesConnectionInputV2<C>,
    ) {
      const prepared = prepareDesktopProjectMemoriesAuthorityOperationV2({
        kind: 'connection',
        ...input,
      });
      return runDesktopProjectMemoriesAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => {
          if (!authority.executeConnection)
            throw projectKnowledgeError('native_knowledge_cloud_connection_unavailable', 503);
          return authority.executeConnection(prepared.command, {
            expectedScope: prepared.expectedScope,
            signal: prepared.signal,
          });
        },
      );
    },
    observeNativeKnowledgeScope(input: DesktopProjectMemoriesObserveScopeInputV2) {
      const prepared = prepareDesktopProjectMemoriesAuthorityOperationV2({
        kind: 'observe-scope',
        ...input,
      });
      return runDesktopProjectMemoriesAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => {
          if (!authority.observeScope)
            throw projectKnowledgeError('native_knowledge_scope_observation_unavailable', 503);
          return authority.observeScope({
            expectedActorId: prepared.expectedActorId,
            signal: prepared.signal,
          });
        },
      );
    },
    queryKnowledgeProcessing<Q extends NativeKnowledgeProcessingQuery>(
      input: DesktopProjectMemoriesProcessingQueryInputV2<Q>,
    ): Promise<NativeKnowledgeProcessingResponse<Q>> {
      const prepared = prepareDesktopProjectMemoriesAuthorityOperationV2({
        kind: 'processing-query',
        ...input,
      });
      return runDesktopProjectMemoriesAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => {
          if (!authority.queryProcessing)
            throw new Error('native_knowledge_processing_unavailable');
          return authority.queryProcessing(prepared.query, {
            signal: prepared.signal,
            expectedScope: prepared.expectedScope,
          } as NativeKnowledgeObservedOptions);
        },
        getCapability,
      );
    },
    executeKnowledgeProcessing<C extends NativeKnowledgeProcessingCommand>(
      input: DesktopProjectMemoriesProcessingCommandInputV2<C>,
    ): Promise<NativeKnowledgeProcessingCommandResponse<C>> {
      const prepared = prepareDesktopProjectMemoriesAuthorityOperationV2({
        kind: 'processing-command',
        ...input,
      });
      return runDesktopProjectMemoriesAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => {
          if (!authority.executeProcessing)
            throw new Error('native_knowledge_processing_unavailable');
          return authority.executeProcessing(prepared.command, {
            signal: prepared.signal,
            expectedScope: prepared.expectedScope,
          } as NativeKnowledgeObservedOptions);
        },
        getCapability,
      );
    },
    executeCloudMemory<C extends CloudMemoryCommand>(
      input: DesktopProjectMemoriesCloudOperationInputV2<C>,
    ): Promise<CloudMemoryResponse<C>> {
      const prepared = prepareDesktopProjectMemoriesAuthorityOperationV2({
        kind: 'cloud',
        ...input,
      });
      return runDesktopProjectMemoriesAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => {
          if (!authority.executeCloudMemory) throw new Error('cloud_memory_authority_unavailable');
          return authority.executeCloudMemory(prepared.command, {
            expectedActorId: prepared.expectedActorId,
            expectedContextRevision: prepared.expectedContextRevision,
            signal: prepared.signal,
          });
        },
      );
    },
    executeKnowledgeSync<C extends NativeKnowledgeCommand>(
      input: DesktopProjectMemoriesSyncOperationInputV2<C>,
    ): Promise<NativeKnowledgeResponse<C>> {
      const prepared = prepareDesktopProjectMemoriesAuthorityOperationV2({
        kind: 'sync',
        ...input,
      });
      return runDesktopProjectMemoriesAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.executeSync(prepared.command, {
            signal: prepared.signal,
            expectedScope: prepared.expectedScope,
          }),
      );
    },
    loadProjectMemories(input: DesktopProjectMemoriesLoadOperationInputV2) {
      const prepared = prepareDesktopProjectMemoriesAuthorityOperationV2({
        kind: 'load',
        ...input,
      });
      return runDesktopProjectMemoriesAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.load(prepared.signal, prepared),
      );
    },
  });
}

export function createDesktopNativeKnowledgeConnectionClientV2(
  operations: Pick<DesktopProjectMemoriesOperationsV2, 'executeKnowledgeConnection'>,
  config: DesktopRuntimeConfig,
): NativeKnowledgeCloudConnectionClient {
  const operationConfig = Object.freeze({ ...config });
  return Object.freeze({
    async execute<C extends NativeKnowledgeCloudConnectionCommand>(
      scope: ProjectKnowledgeScope,
      command: C,
      options: NativeKnowledgeCloudConnectionOptions,
    ) {
      return operations.executeKnowledgeConnection({
        config: operationConfig,
        scope,
        command,
        ...options,
      });
    },
  });
}

export function createDesktopCloudMemoryClientV2(
  operations: Pick<DesktopProjectMemoriesOperationsV2, 'executeCloudMemory'>,
  config: DesktopRuntimeConfig,
): CloudMemoryClient {
  const operationConfig = Object.freeze({ ...config });
  return Object.freeze({
    async execute<C extends CloudMemoryCommand>(
      scope: ProjectKnowledgeScope,
      command: C,
      options: CloudMemoryOptions,
    ): Promise<CloudMemoryResponse<C>> {
      return operations.executeCloudMemory({
        config: operationConfig,
        scope,
        command,
        ...options,
      });
    },
  });
}

export function createDesktopNativeKnowledgeClientV2(
  operations: Pick<
    DesktopProjectMemoriesOperationsV2,
    'executeKnowledgeSync' | 'observeNativeKnowledgeScope'
  >,
  config: DesktopRuntimeConfig,
): NativeKnowledgeClient {
  const operationConfig = Object.freeze({ ...config });
  return Object.freeze({
    observeScope(scope: ProjectKnowledgeScope, options: NativeKnowledgeScopeObservationOptions) {
      return operations.observeNativeKnowledgeScope({
        config: operationConfig,
        scope,
        ...prepareNativeKnowledgeScopeObservationOptions(options),
      });
    },
    execute<C extends NativeKnowledgeCommand>(
      scope: ProjectKnowledgeScope,
      command: C,
      options?: NativeKnowledgeSyncOptions,
    ): Promise<NativeKnowledgeResponse<C>> {
      return operations.executeKnowledgeSync({
        config: operationConfig,
        scope,
        command,
        ...options,
      });
    },
  });
}

export function createDesktopProjectMemoriesClientV2(
  operations: Pick<DesktopProjectMemoriesOperationsV2, 'loadProjectMemories'>,
  config: DesktopRuntimeConfig,
): ProjectMemoriesClient {
  const operationConfig = Object.freeze({ ...config });
  return Object.freeze({
    load(
      scope: Parameters<ProjectMemoriesClient['load']>[0],
      options?: Parameters<ProjectMemoriesClient['load']>[1],
    ) {
      return operations.loadProjectMemories({
        config: operationConfig,
        scope,
        ...(options?.page === undefined ? {} : { page: options.page }),
        ...(options?.pageSize === undefined ? {} : { pageSize: options.pageSize }),
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
  });
}

export function withDesktopProjectMemoriesAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopProjectMemoriesAuthorityOperationInputV2,
  operation: (authority: DesktopProjectMemoriesAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopProjectMemoriesAuthorityOperationV2(
    actions,
    prepareDesktopProjectMemoriesAuthorityOperationV2(input),
    operation,
  );
}

async function runDesktopProjectMemoriesAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedDesktopProjectMemoriesAuthorityOperationV2,
  operation: (authority: DesktopProjectMemoriesAuthorityV2) => TResult | Promise<TResult>,
  getCapability?: NativeKnowledgeProcessingCapabilityGetter,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopProjectMemoriesAuthorityServiceV2>({
      service: DESKTOP_PROJECT_MEMORIES_AUTHORITY_SERVICE_V2,
      version: DESKTOP_PROJECT_MEMORIES_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.scope.tenantId,
        project_id: prepared.scope.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopProjectMemoriesAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireProjectMemoriesServiceV2(candidate);
      const authority = requireProjectMemoriesAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope, getCapability),
      );
      return operation(
        createRevocableProjectMemoriesAuthorityV2(
          authority,
          prepared.scope,
          () => operationActive,
          admission.digest,
        ),
      );
    });
  } catch (error) {
    operationFailed = true;
    throw error;
  } finally {
    operationActive = false;
    try {
      await admission.release();
    } catch (releaseError) {
      if (!operationFailed) throw releaseError;
    }
  }
}

function createRevocableProjectMemoriesAuthorityV2(
  authority: DesktopProjectMemoriesAuthorityV2,
  scope: ProjectKnowledgeScope,
  isOperationActive: () => boolean,
  generationDigest: string,
): DesktopProjectMemoriesAuthorityV2 {
  return Object.freeze({
    ...(authority.executeConnection
      ? {
          async executeConnection<C extends NativeKnowledgeCloudConnectionCommand>(
            command: C,
            inputOptions: NativeKnowledgeCloudConnectionOptions,
          ) {
            const prepared = prepareNativeKnowledgeCloudConnection(command, inputOptions);
            const current = () => {
              requireOperationActiveV2(isOperationActive);
              prepared.options.signal?.throwIfAborted();
              if (prepared.options.expectedScope.digest !== generationDigest)
                throw projectKnowledgeError('knowledge_generation_mismatch', 409);
            };
            current();
            const result = await authority.executeConnection!(
              prepared.command,
              prepared.options,
              current,
            );
            current();
            return requireNativeKnowledgeCloudConnectionResponse(
              result,
              prepared.command,
              scope,
              prepared.options.expectedScope,
            );
          },
        }
      : {}),
    ...(authority.observeScope
      ? {
          async observeScope(input: NativeKnowledgeScopeObservationOptions) {
            const options = prepareNativeKnowledgeScopeObservationOptions(input);
            const current = () => {
              requireOperationActiveV2(isOperationActive);
              options.signal?.throwIfAborted();
            };
            current();
            const result = await authority.observeScope!(options, current);
            current();
            const observed = requireNativeKnowledgeScope(
              { contract_version: '1.0.0', scope: result },
              scope,
            );
            if (observed.digest !== generationDigest)
              throw projectKnowledgeError('knowledge_generation_mismatch', 409);
            return observed;
          },
        }
      : {}),
    ...createRevocableKnowledgeProcessingV2(authority, scope, () =>
      requireOperationActiveV2(isOperationActive),
    ),
    ...(authority.executeCloudMemory
      ? {
          async executeCloudMemory<C extends CloudMemoryCommand>(
            command: C,
            inputOptions: CloudMemoryOptions,
          ): Promise<CloudMemoryResponse<C>> {
            requireOperationActiveV2(isOperationActive);
            const prepared = prepareCloudMemoryCommand(command);
            const options = prepareCloudMemoryOptions(inputOptions);
            options.signal?.throwIfAborted();
            const result = await authority.executeCloudMemory!(prepared, options);
            requireOperationActiveV2(isOperationActive);
            options.signal?.throwIfAborted();
            return requireCloudMemoryResponse(result, prepared, scope);
          },
        }
      : {}),
    async executeSync<C extends NativeKnowledgeCommand>(
      command: C,
      inputOptions?: NativeKnowledgeSyncOptions,
    ): Promise<NativeKnowledgeResponse<C>> {
      requireOperationActiveV2(isOperationActive);
      const prepared = prepareNativeKnowledgeCommand(command);
      const options = requireNativeKnowledgeCommandOptions(prepared, inputOptions);
      options.signal?.throwIfAborted();
      const result = await authority.executeSync(prepared, options);
      requireOperationActiveV2(isOperationActive);
      options.signal?.throwIfAborted();
      return requireNativeKnowledgeResponse(result, prepared, scope, options.expectedScope);
    },
    async load(signal?: AbortSignal, options?: ProjectMemoriesPageOptions) {
      requireOperationActiveV2(isOperationActive);
      const pagination = normalizeDesktopProjectMemoriesPageV2(options);
      signal?.throwIfAborted();
      const result = await authority.load(signal, pagination);
      requireOperationActiveV2(isOperationActive);
      signal?.throwIfAborted();
      return requireDesktopProjectMemoriesSnapshotV2(result, scope, pagination);
    },
  });
}

function requireProjectMemoriesServiceV2(value: unknown): DesktopProjectMemoriesAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectMemoriesAuthorityServiceV2;
}

function requireProjectMemoriesAuthorityV2(value: unknown): DesktopProjectMemoriesAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).some((key) => !AUTHORITY_KEYS_V2.has(key)) ||
    (Object.hasOwn(value, 'executeConnection') && typeof value.executeConnection !== 'function') ||
    (Object.hasOwn(value, 'observeScope') && typeof value.observeScope !== 'function') ||
    (Object.hasOwn(value, 'executeCloudMemory') &&
      typeof value.executeCloudMemory !== 'function') ||
    typeof value.load !== 'function' ||
    typeof value.executeSync !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectMemoriesAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopProjectMemoriesAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireOperationActiveV2(isOperationActive: () => boolean): void {
  if (isOperationActive()) return;
  throw new RuntimeV2Error(
    'desktop_project_memories_operation_released',
    'desktop project memories operation has been released',
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_memories_service_invalid',
    'desktop project memories authority service is invalid',
  );
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === DESKTOP_PROJECT_MEMORIES_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_project_memories_authority_catalog_missing',
      'desktop project memories authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
