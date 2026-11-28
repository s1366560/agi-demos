import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import {
  DesktopApiClient,
  type WorkspaceCreateInput,
  type WorkspaceUpdateInput,
} from '../api/client';
import type { DesktopRuntimeConfig, WorkspaceSummary } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import {
  assertWorkspaceLifecycleSignalV2,
  cloneWorkspaceLifecycleCreateInputV2,
  cloneWorkspaceLifecycleResponseV2,
  cloneWorkspaceLifecycleRuntimeConfigV2,
  cloneWorkspaceLifecycleSignalV2,
  cloneWorkspaceLifecycleUpdateInputV2,
  cloneWorkspaceLifecycleWorkspaceIdV2,
  hasExactOptionalKeysV2,
  isPlainRecordV2,
  workspaceLifecycleInputInvalidV2,
} from './desktopWorkspaceLifecycleContractV2';

export const DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/workspace-lifecycle-authority';
export const DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.workspace-lifecycle-authority';
export const DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_VERSION_V2 = '1.0.0';

export type DesktopWorkspaceLifecycleCreateInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  input: WorkspaceCreateInput;
  signal?: AbortSignal;
}>;

export type DesktopWorkspaceLifecycleUpdateInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  workspaceId: string;
  input: WorkspaceUpdateInput;
  signal?: AbortSignal;
}>;

export interface DesktopWorkspaceLifecycleAuthorityV2 {
  readonly createWorkspace: (
    input: WorkspaceCreateInput,
    signal?: AbortSignal,
  ) => Promise<WorkspaceSummary>;
  readonly updateWorkspace: (
    workspaceId: string,
    input: WorkspaceUpdateInput,
    signal?: AbortSignal,
  ) => Promise<WorkspaceSummary>;
}

export interface DesktopWorkspaceLifecycleAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
  ) => DesktopWorkspaceLifecycleAuthorityV2;
}

export interface DesktopWorkspaceLifecycleOperationsV2 {
  readonly createWorkspace: (
    input: DesktopWorkspaceLifecycleCreateInputV2,
  ) => Promise<WorkspaceSummary>;
  readonly updateWorkspace: (
    input: DesktopWorkspaceLifecycleUpdateInputV2,
  ) => Promise<WorkspaceSummary>;
}

type ServiceAdmissionRejectionV2 = Extract<
  DesktopRendererServiceOperationLeaseAdmissionV2<never>,
  { status: 'rejected' }
>;

type GenerationActionsUnavailableV2 = Readonly<{
  reasonCode: 'desktop_renderer_generation_actions_unavailable';
  runtimeCode?: undefined;
}>;

type AuthorityAdmissionRejectionV2 =
  | ServiceAdmissionRejectionV2
  | GenerationActionsUnavailableV2;

type PreparedWorkspaceLifecycleCreateV2 = Readonly<{
  kind: 'create';
  config: DesktopRuntimeConfig;
  input: WorkspaceCreateInput;
  signal?: AbortSignal;
}>;

type PreparedWorkspaceLifecycleUpdateV2 = Readonly<{
  kind: 'update';
  config: DesktopRuntimeConfig;
  workspaceId: string;
  input: WorkspaceUpdateInput;
  signal?: AbortSignal;
}>;

type PreparedWorkspaceLifecycleOperationV2 =
  | PreparedWorkspaceLifecycleCreateV2
  | PreparedWorkspaceLifecycleUpdateV2;

const CREATE_OPERATION_KEYS_V2 = new Set(['config', 'input', 'signal']);
const UPDATE_OPERATION_KEYS_V2 = new Set(['config', 'input', 'signal', 'workspaceId']);
const AUTHORITY_KEYS_V2 = new Set(['createWorkspace', 'updateWorkspace']);

export class DesktopWorkspaceLifecycleAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopWorkspaceLifecycleAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopWorkspaceLifecycleAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_workspace_lifecycle_authority_config_invalid',
      'desktop workspace lifecycle authority requires desktop-api-client strategy',
    );
  }
  const service: DesktopWorkspaceLifecycleAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopWorkspaceLifecycleAuthorityV2,
  });
  context.provide(DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_SERVICE_V2, service);
}

export const desktopWorkspaceLifecycleAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedContractDigestV2(),
    apply: applyDesktopWorkspaceLifecycleAuthorityV2,
  });

export function createDesktopWorkspaceLifecycleOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopWorkspaceLifecycleOperationsV2 {
  return Object.freeze({
    createWorkspace(input: DesktopWorkspaceLifecycleCreateInputV2) {
      const prepared = prepareCreateOperationV2(input);
      return runDesktopWorkspaceLifecycleAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.createWorkspace(prepared.input, prepared.signal),
      );
    },
    updateWorkspace(input: DesktopWorkspaceLifecycleUpdateInputV2) {
      const prepared = prepareUpdateOperationV2(input);
      return runDesktopWorkspaceLifecycleAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.updateWorkspace(
            prepared.workspaceId,
            prepared.input,
            prepared.signal,
          ),
      );
    },
  });
}

export function withDesktopWorkspaceLifecycleAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopWorkspaceLifecycleCreateInputV2,
  operation: (
    authority: DesktopWorkspaceLifecycleAuthorityV2,
    prepared: PreparedWorkspaceLifecycleCreateV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopWorkspaceLifecycleAuthorityOperationV2(
    actions,
    prepareCreateOperationV2(input),
    operation,
  );
}

async function runDesktopWorkspaceLifecycleAuthorityOperationV2<
  TResult,
  TPrepared extends PreparedWorkspaceLifecycleOperationV2,
>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: TPrepared,
  operation: (
    authority: DesktopWorkspaceLifecycleAuthorityV2,
    prepared: TPrepared,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopWorkspaceLifecycleAuthorityServiceV2>({
      service: DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_SERVICE_V2,
      version: DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.config.tenantId,
        project_id: prepared.config.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopWorkspaceLifecycleAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireWorkspaceLifecycleServiceV2(candidate);
      const authority = requireWorkspaceLifecycleAuthorityV2(
        service.bindOperation(prepared.config),
      );
      return operation(
        createRevocableWorkspaceLifecycleAuthorityV2(
          authority,
          prepared,
          () => operationActive,
        ),
        prepared,
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

function createDesktopWorkspaceLifecycleAuthorityV2(
  config: DesktopRuntimeConfig,
): DesktopWorkspaceLifecycleAuthorityV2 {
  const operationConfig = cloneWorkspaceLifecycleRuntimeConfigV2(config);
  const transport = new DesktopApiClient(operationConfig);
  return Object.freeze({
    createWorkspace(input: WorkspaceCreateInput, signal?: AbortSignal) {
      const command = cloneWorkspaceLifecycleCreateInputV2(input);
      const operationSignal = cloneWorkspaceLifecycleSignalV2(signal);
      return transport
        .createWorkspaceForProject(
          operationConfig.projectId,
          command,
          operationConfig.tenantId,
          operationSignal,
        )
        .then((value) =>
          cloneWorkspaceLifecycleResponseV2(
            value,
            operationConfig,
            null,
            command.name,
          ),
        );
    },
    updateWorkspace(
      workspaceId: string,
      input: WorkspaceUpdateInput,
      signal?: AbortSignal,
    ) {
      const operationWorkspaceId = cloneWorkspaceLifecycleWorkspaceIdV2(workspaceId);
      if (operationWorkspaceId !== operationConfig.workspaceId) {
        throw workspaceLifecycleInputInvalidV2();
      }
      const command = cloneWorkspaceLifecycleUpdateInputV2(input);
      const operationSignal = cloneWorkspaceLifecycleSignalV2(signal);
      return transport
        .updateWorkspaceForProject(
          operationConfig.projectId,
          operationWorkspaceId,
          command,
          operationConfig.tenantId,
          operationSignal,
        )
        .then((value) =>
          cloneWorkspaceLifecycleResponseV2(
            value,
            operationConfig,
            operationWorkspaceId,
            command.name,
          ),
        );
    },
  });
}

function createRevocableWorkspaceLifecycleAuthorityV2(
  authority: DesktopWorkspaceLifecycleAuthorityV2,
  prepared: PreparedWorkspaceLifecycleOperationV2,
  isOperationActive: () => boolean,
): DesktopWorkspaceLifecycleAuthorityV2 {
  let mutationStarted = false;
  return Object.freeze({
    createWorkspace(input: WorkspaceCreateInput, signal?: AbortSignal) {
      assertOperationActiveV2(isOperationActive);
      if (prepared.kind !== 'create' || mutationStarted) {
        throw workspaceLifecycleInputInvalidV2();
      }
      const command = cloneWorkspaceLifecycleCreateInputV2(input);
      const operationSignal = cloneWorkspaceLifecycleSignalV2(signal);
      assertWorkspaceLifecycleSignalV2(prepared.signal, operationSignal);
      if (JSON.stringify(command) !== JSON.stringify(prepared.input)) {
        throw workspaceLifecycleInputInvalidV2();
      }
      mutationStarted = true;
      return Promise.resolve(authority.createWorkspace(command, operationSignal)).then(
        (value) =>
          cloneWorkspaceLifecycleResponseV2(
            value,
            prepared.config,
            null,
            prepared.input.name,
          ),
      );
    },
    updateWorkspace(
      workspaceId: string,
      input: WorkspaceUpdateInput,
      signal?: AbortSignal,
    ) {
      assertOperationActiveV2(isOperationActive);
      if (prepared.kind !== 'update' || mutationStarted) {
        throw workspaceLifecycleInputInvalidV2();
      }
      const operationWorkspaceId = cloneWorkspaceLifecycleWorkspaceIdV2(workspaceId);
      const command = cloneWorkspaceLifecycleUpdateInputV2(input);
      const operationSignal = cloneWorkspaceLifecycleSignalV2(signal);
      assertWorkspaceLifecycleSignalV2(prepared.signal, operationSignal);
      if (
        operationWorkspaceId !== prepared.workspaceId ||
        JSON.stringify(command) !== JSON.stringify(prepared.input)
      ) {
        throw workspaceLifecycleInputInvalidV2();
      }
      mutationStarted = true;
      return Promise.resolve(
        authority.updateWorkspace(operationWorkspaceId, command, operationSignal),
      ).then((value) =>
        cloneWorkspaceLifecycleResponseV2(
          value,
          prepared.config,
          prepared.workspaceId,
          prepared.input.name,
        ),
      );
    },
  });
}

function prepareCreateOperationV2(
  input: DesktopWorkspaceLifecycleCreateInputV2,
): PreparedWorkspaceLifecycleCreateV2 {
  assertOperationInputShapeV2(input, CREATE_OPERATION_KEYS_V2, []);
  const config = cloneWorkspaceLifecycleRuntimeConfigV2(input.config);
  if (config.workspaceId !== '') throw workspaceLifecycleInputInvalidV2();
  return Object.freeze({
    kind: 'create',
    config,
    input: cloneWorkspaceLifecycleCreateInputV2(input.input),
    ...(input.signal === undefined
      ? {}
      : { signal: cloneWorkspaceLifecycleSignalV2(input.signal) }),
  });
}

function prepareUpdateOperationV2(
  input: DesktopWorkspaceLifecycleUpdateInputV2,
): PreparedWorkspaceLifecycleUpdateV2 {
  assertOperationInputShapeV2(input, UPDATE_OPERATION_KEYS_V2, ['workspaceId']);
  const config = cloneWorkspaceLifecycleRuntimeConfigV2(input.config);
  const workspaceId = cloneWorkspaceLifecycleWorkspaceIdV2(input.workspaceId);
  if (config.workspaceId !== workspaceId) throw workspaceLifecycleInputInvalidV2();
  return Object.freeze({
    kind: 'update',
    config,
    workspaceId,
    input: cloneWorkspaceLifecycleUpdateInputV2(input.input),
    ...(input.signal === undefined
      ? {}
      : { signal: cloneWorkspaceLifecycleSignalV2(input.signal) }),
  });
}

function assertOperationInputShapeV2(
  input: unknown,
  allowedKeys: ReadonlySet<string>,
  additionalRequiredKeys: readonly string[],
): asserts input is Record<string, unknown> & {
  config: DesktopRuntimeConfig;
  input: WorkspaceCreateInput | WorkspaceUpdateInput;
} {
  if (
    !isPlainRecordV2(input) ||
    !hasExactOptionalKeysV2(input, allowedKeys) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'input') ||
    additionalRequiredKeys.some((key) => !Object.hasOwn(input, key))
  ) {
    throw workspaceLifecycleInputInvalidV2();
  }
}

function assertOperationActiveV2(isOperationActive: () => boolean): void {
  if (!isOperationActive()) {
    throw new RuntimeV2Error(
      'desktop_workspace_lifecycle_operation_released',
      'desktop workspace lifecycle operation has been released',
    );
  }
}

function requireWorkspaceLifecycleServiceV2(
  value: unknown,
): DesktopWorkspaceLifecycleAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidWorkspaceLifecycleServiceV2();
  }
  return value as unknown as DesktopWorkspaceLifecycleAuthorityServiceV2;
}

function requireWorkspaceLifecycleAuthorityV2(
  value: unknown,
): DesktopWorkspaceLifecycleAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== AUTHORITY_KEYS_V2.size ||
    !Object.keys(value).every((key) => AUTHORITY_KEYS_V2.has(key)) ||
    typeof value.createWorkspace !== 'function' ||
    typeof value.updateWorkspace !== 'function'
  ) {
    throw invalidWorkspaceLifecycleServiceV2();
  }
  return value as unknown as DesktopWorkspaceLifecycleAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopWorkspaceLifecycleAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function invalidWorkspaceLifecycleServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_lifecycle_service_invalid',
    'desktop workspace lifecycle authority service is invalid',
  );
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) =>
      candidate.module_ref === DESKTOP_WORKSPACE_LIFECYCLE_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_workspace_lifecycle_authority_catalog_missing',
      'desktop workspace lifecycle authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
