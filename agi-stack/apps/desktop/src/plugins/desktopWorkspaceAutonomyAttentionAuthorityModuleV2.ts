import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import { DesktopApiClient } from '../api/client';
import type {
  DesktopRuntimeConfig,
  WorkspaceAutonomyAttention,
  WorkspaceAutonomyAttentionResolveResponse,
  WorkspaceAutonomyAttentionRetryResponse,
} from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import {
  assertWorkspaceAutonomyAttentionSignalV2,
  cloneWorkspaceAutonomyAttentionActorIdV2,
  cloneWorkspaceAutonomyAttentionExpectedRevisionV2,
  cloneWorkspaceAutonomyAttentionIdempotencyKeyV2,
  cloneWorkspaceAutonomyAttentionIdV2,
  cloneWorkspaceAutonomyAttentionResolveResponseV2,
  cloneWorkspaceAutonomyAttentionRetryResponseV2,
  cloneWorkspaceAutonomyAttentionRevisionV2,
  cloneWorkspaceAutonomyAttentionRuntimeConfigV2,
  cloneWorkspaceAutonomyAttentionsV2,
  cloneWorkspaceAutonomyAttentionSignalV2,
  cloneWorkspaceAutonomyAttentionWorkspaceIdV2,
  hasExactOptionalKeysV2,
  isPlainRecordV2,
  workspaceAutonomyAttentionInputInvalidV2,
} from './desktopWorkspaceAutonomyAttentionContractV2';

export const DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/workspace-autonomy-attention-authority';
export const DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.workspace-autonomy-attention-authority';
export const DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_VERSION_V2 = '1.0.0';

export type DesktopWorkspaceAutonomyAttentionListInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  workspaceId: string;
  signal?: AbortSignal;
}>;

export type DesktopWorkspaceAutonomyAttentionRetryInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  workspaceId: string;
  attentionId: string;
  signal?: AbortSignal;
}>;

export type DesktopWorkspaceAutonomyAttentionResolveInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  workspaceId: string;
  actorId: string;
  attentionId: string;
  expectedRevision: number | null;
  idempotencyKey: string;
  signal?: AbortSignal;
}>;

export type PreparedDesktopWorkspaceAutonomyAttentionListV2 = Readonly<{
  kind: 'list';
  config: DesktopRuntimeConfig;
  workspaceId: string;
  signal?: AbortSignal;
}>;

export type PreparedDesktopWorkspaceAutonomyAttentionRetryV2 = Readonly<{
  kind: 'retry';
  config: DesktopRuntimeConfig;
  workspaceId: string;
  attentionId: string;
  signal?: AbortSignal;
}>;

export type PreparedDesktopWorkspaceAutonomyAttentionResolveV2 = Readonly<{
  kind: 'resolve';
  config: DesktopRuntimeConfig;
  workspaceId: string;
  actorId: string;
  attentionId: string;
  expectedRevision: number | null;
  idempotencyKey: string;
  signal?: AbortSignal;
}>;

type PreparedDesktopWorkspaceAutonomyAttentionOperationV2 =
  | PreparedDesktopWorkspaceAutonomyAttentionListV2
  | PreparedDesktopWorkspaceAutonomyAttentionRetryV2
  | PreparedDesktopWorkspaceAutonomyAttentionResolveV2;

export interface DesktopWorkspaceAutonomyAttentionAuthorityV2 {
  readonly listWorkspaceAutonomyAttentions: (
    signal?: AbortSignal,
  ) => Promise<WorkspaceAutonomyAttention[]>;
  readonly getWorkspaceAuthorityRevision: (signal?: AbortSignal) => Promise<number>;
  readonly retryWorkspaceAutonomyAttention: (
    attentionId: string,
    signal?: AbortSignal,
  ) => Promise<WorkspaceAutonomyAttentionRetryResponse>;
  readonly resolveWorkspaceAutonomyAttention: (
    attentionId: string,
    expectedRevision: number,
    idempotencyKey: string,
    signal?: AbortSignal,
  ) => Promise<WorkspaceAutonomyAttentionResolveResponse>;
}

export interface DesktopWorkspaceAutonomyAttentionAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    workspaceId: string,
  ) => DesktopWorkspaceAutonomyAttentionAuthorityV2;
}

export interface DesktopWorkspaceAutonomyAttentionOperationsV2 {
  readonly listWorkspaceAutonomyAttentions: (
    input: DesktopWorkspaceAutonomyAttentionListInputV2,
  ) => Promise<WorkspaceAutonomyAttention[]>;
  readonly withRetryWorkspaceAutonomyAttention: <TResult>(
    input: DesktopWorkspaceAutonomyAttentionRetryInputV2,
    operation: (
      authority: DesktopWorkspaceAutonomyAttentionAuthorityV2,
      prepared: PreparedDesktopWorkspaceAutonomyAttentionRetryV2,
    ) => TResult | Promise<TResult>,
  ) => Promise<TResult>;
  readonly withResolveWorkspaceAutonomyAttention: <TResult>(
    input: DesktopWorkspaceAutonomyAttentionResolveInputV2,
    operation: (
      authority: DesktopWorkspaceAutonomyAttentionAuthorityV2,
      prepared: PreparedDesktopWorkspaceAutonomyAttentionResolveV2,
    ) => TResult | Promise<TResult>,
  ) => Promise<TResult>;
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

const LIST_INPUT_KEYS_V2 = new Set(['config', 'signal', 'workspaceId']);
const RETRY_INPUT_KEYS_V2 = new Set(['attentionId', 'config', 'signal', 'workspaceId']);
const RESOLVE_INPUT_KEYS_V2 = new Set([
  'actorId',
  'attentionId',
  'config',
  'expectedRevision',
  'idempotencyKey',
  'signal',
  'workspaceId',
]);
const AUTHORITY_KEYS_V2 = new Set([
  'getWorkspaceAuthorityRevision',
  'listWorkspaceAutonomyAttentions',
  'resolveWorkspaceAutonomyAttention',
  'retryWorkspaceAutonomyAttention',
]);

export class DesktopWorkspaceAutonomyAttentionAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopWorkspaceAutonomyAttentionAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopWorkspaceAutonomyAttentionAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_workspace_autonomy_attention_authority_config_invalid',
      'desktop workspace autonomy-attention authority requires desktop-api-client strategy',
    );
  }
  const service: DesktopWorkspaceAutonomyAttentionAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopWorkspaceAutonomyAttentionAuthorityV2,
  });
  context.provide(DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_SERVICE_V2, service);
}

export const desktopWorkspaceAutonomyAttentionAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedContractDigestV2(),
    apply: applyDesktopWorkspaceAutonomyAttentionAuthorityV2,
  });

export function createDesktopWorkspaceAutonomyAttentionOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopWorkspaceAutonomyAttentionOperationsV2 {
  return Object.freeze({
    listWorkspaceAutonomyAttentions(input: DesktopWorkspaceAutonomyAttentionListInputV2) {
      const prepared = prepareListOperationV2(input);
      return runDesktopWorkspaceAutonomyAttentionAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.listWorkspaceAutonomyAttentions(prepared.signal),
      );
    },
    withRetryWorkspaceAutonomyAttention<TResult>(
      input: DesktopWorkspaceAutonomyAttentionRetryInputV2,
      operation: (
        authority: DesktopWorkspaceAutonomyAttentionAuthorityV2,
        prepared: PreparedDesktopWorkspaceAutonomyAttentionRetryV2,
      ) => TResult | Promise<TResult>,
    ) {
      if (typeof operation !== 'function') throw workspaceAutonomyAttentionInputInvalidV2();
      const prepared = prepareRetryOperationV2(input);
      return runDesktopWorkspaceAutonomyAttentionAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        operation,
      );
    },
    withResolveWorkspaceAutonomyAttention<TResult>(
      input: DesktopWorkspaceAutonomyAttentionResolveInputV2,
      operation: (
        authority: DesktopWorkspaceAutonomyAttentionAuthorityV2,
        prepared: PreparedDesktopWorkspaceAutonomyAttentionResolveV2,
      ) => TResult | Promise<TResult>,
    ) {
      if (typeof operation !== 'function') throw workspaceAutonomyAttentionInputInvalidV2();
      const prepared = prepareResolveOperationV2(input);
      return runDesktopWorkspaceAutonomyAttentionAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        operation,
      );
    },
  });
}

async function runDesktopWorkspaceAutonomyAttentionAuthorityOperationV2<
  TResult,
  TPrepared extends PreparedDesktopWorkspaceAutonomyAttentionOperationV2,
>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: TPrepared,
  operation: (
    authority: DesktopWorkspaceAutonomyAttentionAuthorityV2,
    prepared: TPrepared,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopWorkspaceAutonomyAttentionAuthorityServiceV2>(
      {
        service: DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_SERVICE_V2,
        version: DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_VERSION_V2,
        scope: Object.freeze({
          kind: 'project',
          tenant_id: prepared.config.tenantId,
          project_id: prepared.config.projectId,
        }),
      },
    );
  if (admission.status === 'rejected') {
    throw new DesktopWorkspaceAutonomyAttentionAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireWorkspaceAutonomyAttentionServiceV2(candidate);
      const authority = requireWorkspaceAutonomyAttentionAuthorityV2(
        service.bindOperation(prepared.config, prepared.workspaceId),
      );
      return operation(
        createRevocableWorkspaceAutonomyAttentionAuthorityV2(
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

function createDesktopWorkspaceAutonomyAttentionAuthorityV2(
  config: DesktopRuntimeConfig,
  workspaceId: string,
): DesktopWorkspaceAutonomyAttentionAuthorityV2 {
  const operationConfig = cloneWorkspaceAutonomyAttentionRuntimeConfigV2(config);
  cloneWorkspaceAutonomyAttentionWorkspaceIdV2(operationConfig, workspaceId);
  const transport = new DesktopApiClient(operationConfig);
  return Object.freeze({
    listWorkspaceAutonomyAttentions(signal?: AbortSignal) {
      const operationSignal = cloneWorkspaceAutonomyAttentionSignalV2(signal);
      return transport
        .listWorkspaceAutonomyAttentions(operationSignal)
        .then(cloneWorkspaceAutonomyAttentionsV2);
    },
    getWorkspaceAuthorityRevision(signal?: AbortSignal) {
      const operationSignal = cloneWorkspaceAutonomyAttentionSignalV2(signal);
      return transport
        .getWorkspaceAuthorityRevision(operationSignal)
        .then(cloneWorkspaceAutonomyAttentionRevisionV2);
    },
    retryWorkspaceAutonomyAttention(attentionId: string, signal?: AbortSignal) {
      const operationAttentionId = cloneWorkspaceAutonomyAttentionIdV2(attentionId);
      const operationSignal = cloneWorkspaceAutonomyAttentionSignalV2(signal);
      return transport
        .retryWorkspaceAutonomyAttention(operationAttentionId, operationSignal)
        .then((value) =>
          cloneWorkspaceAutonomyAttentionRetryResponseV2(value, operationAttentionId),
        );
    },
    resolveWorkspaceAutonomyAttention(
      attentionId: string,
      expectedRevision: number,
      idempotencyKey: string,
      signal?: AbortSignal,
    ) {
      const operationAttentionId = cloneWorkspaceAutonomyAttentionIdV2(attentionId);
      const operationRevision = cloneRequiredExpectedRevisionV2(expectedRevision);
      const operationIdempotencyKey =
        cloneWorkspaceAutonomyAttentionIdempotencyKeyV2(idempotencyKey);
      const operationSignal = cloneWorkspaceAutonomyAttentionSignalV2(signal);
      return transport
        .resolveWorkspaceAutonomyAttention(
          operationAttentionId,
          operationRevision,
          operationIdempotencyKey,
          operationSignal,
        )
        .then((value) =>
          cloneWorkspaceAutonomyAttentionResolveResponseV2(value, operationAttentionId),
        );
    },
  });
}

function createRevocableWorkspaceAutonomyAttentionAuthorityV2(
  authority: DesktopWorkspaceAutonomyAttentionAuthorityV2,
  prepared: PreparedDesktopWorkspaceAutonomyAttentionOperationV2,
  isOperationActive: () => boolean,
): DesktopWorkspaceAutonomyAttentionAuthorityV2 {
  let observedRevision =
    prepared.kind === 'resolve' ? prepared.expectedRevision : null;
  let retryStarted = false;
  let resolveStarted = false;
  return Object.freeze({
    listWorkspaceAutonomyAttentions(signal?: AbortSignal) {
      assertWorkspaceAutonomyAttentionOperationActiveV2(isOperationActive);
      const operationSignal = cloneWorkspaceAutonomyAttentionSignalV2(signal);
      assertWorkspaceAutonomyAttentionSignalV2(prepared.signal, operationSignal);
      return Promise.resolve(authority.listWorkspaceAutonomyAttentions(operationSignal)).then(
        cloneWorkspaceAutonomyAttentionsV2,
      );
    },
    getWorkspaceAuthorityRevision(signal?: AbortSignal) {
      assertWorkspaceAutonomyAttentionOperationActiveV2(isOperationActive);
      if (
        prepared.kind !== 'resolve' ||
        prepared.expectedRevision !== null ||
        observedRevision !== null
      ) {
        throw workspaceAutonomyAttentionInputInvalidV2();
      }
      const operationSignal = cloneWorkspaceAutonomyAttentionSignalV2(signal);
      assertWorkspaceAutonomyAttentionSignalV2(prepared.signal, operationSignal);
      return Promise.resolve(authority.getWorkspaceAuthorityRevision(operationSignal)).then(
        (value) => {
          const revision = cloneWorkspaceAutonomyAttentionRevisionV2(value);
          observedRevision = revision;
          return revision;
        },
      );
    },
    retryWorkspaceAutonomyAttention(attentionId: string, signal?: AbortSignal) {
      assertWorkspaceAutonomyAttentionOperationActiveV2(isOperationActive);
      if (prepared.kind !== 'retry' || retryStarted) {
        throw workspaceAutonomyAttentionInputInvalidV2();
      }
      const operationAttentionId = cloneWorkspaceAutonomyAttentionIdV2(attentionId);
      const operationSignal = cloneWorkspaceAutonomyAttentionSignalV2(signal);
      if (operationAttentionId !== prepared.attentionId) {
        throw workspaceAutonomyAttentionInputInvalidV2();
      }
      assertWorkspaceAutonomyAttentionSignalV2(prepared.signal, operationSignal);
      retryStarted = true;
      return Promise.resolve(
        authority.retryWorkspaceAutonomyAttention(operationAttentionId, operationSignal),
      ).then((value) =>
        cloneWorkspaceAutonomyAttentionRetryResponseV2(value, operationAttentionId),
      );
    },
    resolveWorkspaceAutonomyAttention(
      attentionId: string,
      expectedRevision: number,
      idempotencyKey: string,
      signal?: AbortSignal,
    ) {
      assertWorkspaceAutonomyAttentionOperationActiveV2(isOperationActive);
      if (prepared.kind !== 'resolve' || resolveStarted) {
        throw workspaceAutonomyAttentionInputInvalidV2();
      }
      const operationAttentionId = cloneWorkspaceAutonomyAttentionIdV2(attentionId);
      const operationRevision = cloneRequiredExpectedRevisionV2(expectedRevision);
      const operationIdempotencyKey =
        cloneWorkspaceAutonomyAttentionIdempotencyKeyV2(idempotencyKey);
      const operationSignal = cloneWorkspaceAutonomyAttentionSignalV2(signal);
      if (
        operationAttentionId !== prepared.attentionId ||
        operationIdempotencyKey !== prepared.idempotencyKey ||
        observedRevision === null ||
        operationRevision !== observedRevision
      ) {
        throw workspaceAutonomyAttentionInputInvalidV2();
      }
      assertWorkspaceAutonomyAttentionSignalV2(prepared.signal, operationSignal);
      resolveStarted = true;
      return Promise.resolve(
        authority.resolveWorkspaceAutonomyAttention(
          operationAttentionId,
          operationRevision,
          operationIdempotencyKey,
          operationSignal,
        ),
      ).then((value) =>
        cloneWorkspaceAutonomyAttentionResolveResponseV2(value, operationAttentionId),
      );
    },
  });
}

function prepareListOperationV2(
  input: DesktopWorkspaceAutonomyAttentionListInputV2,
): PreparedDesktopWorkspaceAutonomyAttentionListV2 {
  assertInputShapeV2(input, LIST_INPUT_KEYS_V2, []);
  const config = cloneWorkspaceAutonomyAttentionRuntimeConfigV2(input.config);
  return Object.freeze({
    kind: 'list',
    config,
    workspaceId: cloneWorkspaceAutonomyAttentionWorkspaceIdV2(config, input.workspaceId),
    ...(input.signal === undefined
      ? {}
      : { signal: cloneWorkspaceAutonomyAttentionSignalV2(input.signal) }),
  });
}

function prepareRetryOperationV2(
  input: DesktopWorkspaceAutonomyAttentionRetryInputV2,
): PreparedDesktopWorkspaceAutonomyAttentionRetryV2 {
  assertInputShapeV2(input, RETRY_INPUT_KEYS_V2, ['attentionId']);
  const config = cloneWorkspaceAutonomyAttentionRuntimeConfigV2(input.config);
  return Object.freeze({
    kind: 'retry',
    config,
    workspaceId: cloneWorkspaceAutonomyAttentionWorkspaceIdV2(config, input.workspaceId),
    attentionId: cloneWorkspaceAutonomyAttentionIdV2(input.attentionId),
    ...(input.signal === undefined
      ? {}
      : { signal: cloneWorkspaceAutonomyAttentionSignalV2(input.signal) }),
  });
}

function prepareResolveOperationV2(
  input: DesktopWorkspaceAutonomyAttentionResolveInputV2,
): PreparedDesktopWorkspaceAutonomyAttentionResolveV2 {
  assertInputShapeV2(input, RESOLVE_INPUT_KEYS_V2, [
    'actorId',
    'attentionId',
    'expectedRevision',
    'idempotencyKey',
  ]);
  const config = cloneWorkspaceAutonomyAttentionRuntimeConfigV2(input.config);
  return Object.freeze({
    kind: 'resolve',
    config,
    workspaceId: cloneWorkspaceAutonomyAttentionWorkspaceIdV2(config, input.workspaceId),
    actorId: cloneWorkspaceAutonomyAttentionActorIdV2(input.actorId),
    attentionId: cloneWorkspaceAutonomyAttentionIdV2(input.attentionId),
    expectedRevision: cloneWorkspaceAutonomyAttentionExpectedRevisionV2(
      input.expectedRevision,
    ),
    idempotencyKey: cloneWorkspaceAutonomyAttentionIdempotencyKeyV2(
      input.idempotencyKey,
    ),
    ...(input.signal === undefined
      ? {}
      : { signal: cloneWorkspaceAutonomyAttentionSignalV2(input.signal) }),
  });
}

function assertInputShapeV2(
  input: unknown,
  allowedKeys: ReadonlySet<string>,
  additionalRequiredKeys: readonly string[],
): asserts input is Record<string, unknown> & {
  config: DesktopRuntimeConfig;
  workspaceId: string;
} {
  if (
    !isPlainRecordV2(input) ||
    !hasExactOptionalKeysV2(input, allowedKeys) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'workspaceId') ||
    additionalRequiredKeys.some((key) => !Object.hasOwn(input, key))
  ) {
    throw workspaceAutonomyAttentionInputInvalidV2();
  }
}

function cloneRequiredExpectedRevisionV2(value: unknown): number {
  const revision = cloneWorkspaceAutonomyAttentionExpectedRevisionV2(value);
  if (revision === null) throw workspaceAutonomyAttentionInputInvalidV2();
  return revision;
}

function assertWorkspaceAutonomyAttentionOperationActiveV2(
  isOperationActive: () => boolean,
): void {
  if (!isOperationActive()) {
    throw new RuntimeV2Error(
      'desktop_workspace_autonomy_attention_operation_released',
      'desktop workspace autonomy-attention operation has been released',
    );
  }
}

function requireWorkspaceAutonomyAttentionServiceV2(
  value: unknown,
): DesktopWorkspaceAutonomyAttentionAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidWorkspaceAutonomyAttentionServiceV2();
  }
  return value as unknown as DesktopWorkspaceAutonomyAttentionAuthorityServiceV2;
}

function requireWorkspaceAutonomyAttentionAuthorityV2(
  value: unknown,
): DesktopWorkspaceAutonomyAttentionAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== AUTHORITY_KEYS_V2.size ||
    !Object.keys(value).every((key) => AUTHORITY_KEYS_V2.has(key)) ||
    typeof value.listWorkspaceAutonomyAttentions !== 'function' ||
    typeof value.getWorkspaceAuthorityRevision !== 'function' ||
    typeof value.retryWorkspaceAutonomyAttention !== 'function' ||
    typeof value.resolveWorkspaceAutonomyAttention !== 'function'
  ) {
    throw invalidWorkspaceAutonomyAttentionServiceV2();
  }
  return value as unknown as DesktopWorkspaceAutonomyAttentionAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopWorkspaceAutonomyAttentionAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function invalidWorkspaceAutonomyAttentionServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_autonomy_attention_service_invalid',
    'desktop workspace autonomy-attention authority service is invalid',
  );
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) =>
      candidate.module_ref === DESKTOP_WORKSPACE_AUTONOMY_ATTENTION_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_workspace_autonomy_attention_authority_catalog_missing',
      'desktop workspace autonomy-attention authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
