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
} from '../features/project-knowledge/nativeKnowledgeContracts';
import {
  prepareNativeKnowledgeCommand,
  requireNativeKnowledgeCommandOptions,
  requireNativeKnowledgeResponse,
} from '../features/project-knowledge/nativeKnowledgeValidation';
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

export interface DesktopProjectMemoriesAuthorityV2 extends NativeKnowledgeSyncAuthority {
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
  ) => DesktopProjectMemoriesAuthorityV2;
}

export interface DesktopProjectMemoriesOperationsV2 {
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

const AUTHORITY_KEYS_V2 = new Set(['load', 'executeSync', 'executeCloudMemory']);

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
): DesktopProjectMemoriesOperationsV2 {
  return Object.freeze({
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
      return operations.executeCloudMemory({ config: operationConfig, scope, command, ...options });
    },
  });
}

export function createDesktopNativeKnowledgeClientV2(
  operations: Pick<DesktopProjectMemoriesOperationsV2, 'executeKnowledgeSync'>,
  config: DesktopRuntimeConfig,
): NativeKnowledgeClient {
  const operationConfig = Object.freeze({ ...config });
  return Object.freeze({
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
        service.bindOperation(prepared.config, prepared.scope),
      );
      return operation(
        createRevocableProjectMemoriesAuthorityV2(authority, prepared.scope, () => operationActive),
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
): DesktopProjectMemoriesAuthorityV2 {
  return Object.freeze({
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
