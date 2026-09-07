import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import { DesktopApiClient } from '../api/client';
import type {
  AgentConversation,
  CreateRunInputRequest,
  DesktopRuntimeConfig,
  RunInputAck,
} from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import {
  assertSessionRunInputScopeV2,
  cloneSessionRunInputAckV2,
  cloneSessionRunInputCreateRequestV2,
  cloneSessionRunInputIdentifierV2,
  cloneSessionRunInputIdentityV2,
  cloneSessionRunInputListResponseV2,
  cloneSessionRunInputPromotionResponseV2,
  cloneSessionRunInputRevisionV2,
  cloneSessionRunInputRuntimeConfigV2,
  cloneSessionRunInputServiceIdentityV2,
  cloneSessionRunInputSignalV2,
  hasExactKeysV2,
  isPlainRecordV2,
  sessionRunInputInputInvalidV2,
  type DesktopSessionRunInputIdentityV2,
  type DesktopSessionRunInputListResponseV2,
  type DesktopSessionRunInputPromotionResponseV2,
} from './desktopSessionRunInputContractV2';

export const DESKTOP_SESSION_RUN_INPUT_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/session-run-input-authority';
export const DESKTOP_SESSION_RUN_INPUT_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.session-run-input-authority';
export const DESKTOP_SESSION_RUN_INPUT_AUTHORITY_VERSION_V2 = '1.0.0';

export type DesktopSessionRunInputCreateOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  conversation: Pick<
    AgentConversation,
    'id' | 'tenant_id' | 'project_id' | 'workspace_id'
  >;
  runId: string;
  request: CreateRunInputRequest;
  signal?: AbortSignal;
}>;

export type DesktopSessionRunInputListOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  conversation: Pick<
    AgentConversation,
    'id' | 'tenant_id' | 'project_id' | 'workspace_id'
  >;
  runId: string;
  signal?: AbortSignal;
}>;

export type DesktopSessionRunInputPromoteOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  conversation: Pick<
    AgentConversation,
    'id' | 'tenant_id' | 'project_id' | 'workspace_id'
  >;
  runId: string;
  inputId: string;
  expectedSourceRunRevision: number;
  idempotencyKey: string;
  signal?: AbortSignal;
}>;

export type DesktopSessionRunInputOperationInputV2 =
  | (DesktopSessionRunInputCreateOperationInputV2 & Readonly<{ kind: 'create' }>)
  | (DesktopSessionRunInputListOperationInputV2 & Readonly<{ kind: 'list' }>)
  | (DesktopSessionRunInputPromoteOperationInputV2 & Readonly<{ kind: 'promote' }>);

export interface DesktopSessionRunInputAuthorityV2 {
  readonly createRunInput: (
    runId: string,
    request: CreateRunInputRequest,
    signal?: AbortSignal,
  ) => Promise<RunInputAck>;
  readonly listRunInputs: (
    runId: string,
    signal?: AbortSignal,
  ) => Promise<DesktopSessionRunInputListResponseV2>;
  readonly promoteRunInput: (
    runId: string,
    inputId: string,
    expectedSourceRunRevision: number,
    idempotencyKey: string,
    signal?: AbortSignal,
  ) => Promise<DesktopSessionRunInputPromotionResponseV2>;
}

export interface DesktopSessionRunInputAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    identity: DesktopSessionRunInputIdentityV2,
  ) => DesktopSessionRunInputAuthorityV2;
}

export interface DesktopSessionRunInputOperationsV2 {
  readonly createRunInput: (
    input: DesktopSessionRunInputCreateOperationInputV2,
  ) => Promise<RunInputAck>;
  readonly listRunInputs: (
    input: DesktopSessionRunInputListOperationInputV2,
  ) => Promise<DesktopSessionRunInputListResponseV2>;
  readonly promoteRunInput: (
    input: DesktopSessionRunInputPromoteOperationInputV2,
  ) => Promise<DesktopSessionRunInputPromotionResponseV2>;
}

type PreparedSessionRunInputOperationV2 =
  | Readonly<{
      kind: 'create';
      config: DesktopRuntimeConfig;
      identity: DesktopSessionRunInputIdentityV2;
      runId: string;
      request: CreateRunInputRequest;
      signal?: AbortSignal;
    }>
  | Readonly<{
      kind: 'list';
      config: DesktopRuntimeConfig;
      identity: DesktopSessionRunInputIdentityV2;
      runId: string;
      signal?: AbortSignal;
    }>
  | Readonly<{
      kind: 'promote';
      config: DesktopRuntimeConfig;
      identity: DesktopSessionRunInputIdentityV2;
      runId: string;
      inputId: string;
      expectedSourceRunRevision: number;
      idempotencyKey: string;
      signal?: AbortSignal;
    }>;

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

const CREATE_INPUT_KEYS_V2 = new Set([
  'kind',
  'config',
  'conversation',
  'runId',
  'request',
  'signal',
]);
const LIST_INPUT_KEYS_V2 = new Set([
  'kind',
  'config',
  'conversation',
  'runId',
  'signal',
]);
const PROMOTE_INPUT_KEYS_V2 = new Set([
  'kind',
  'config',
  'conversation',
  'runId',
  'inputId',
  'expectedSourceRunRevision',
  'idempotencyKey',
  'signal',
]);
const AUTHORITY_KEYS_V2 = new Set([
  'createRunInput',
  'listRunInputs',
  'promoteRunInput',
]);

export class DesktopSessionRunInputAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopSessionRunInputAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopSessionRunInputAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_session_run_input_authority_config_invalid',
      'desktop session run-input authority requires desktop-api-client strategy',
    );
  }
  const service: DesktopSessionRunInputAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopSessionRunInputAuthorityV2,
  });
  context.provide(DESKTOP_SESSION_RUN_INPUT_AUTHORITY_SERVICE_V2, service);
}

export const desktopSessionRunInputAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_SESSION_RUN_INPUT_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopSessionRunInputAuthorityV2,
});

export function createDesktopSessionRunInputOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopSessionRunInputOperationsV2 {
  return Object.freeze({
    createRunInput(input: DesktopSessionRunInputCreateOperationInputV2) {
      const prepared = prepareSessionRunInputOperationV2({ kind: 'create', ...input });
      if (prepared.kind !== 'create') throw sessionRunInputInputInvalidV2();
      return runDesktopSessionRunInputAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.createRunInput(
            prepared.runId,
            prepared.request,
            prepared.signal,
          ),
      );
    },
    listRunInputs(input: DesktopSessionRunInputListOperationInputV2) {
      const prepared = prepareSessionRunInputOperationV2({ kind: 'list', ...input });
      if (prepared.kind !== 'list') throw sessionRunInputInputInvalidV2();
      return runDesktopSessionRunInputAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.listRunInputs(prepared.runId, prepared.signal),
      );
    },
    promoteRunInput(input: DesktopSessionRunInputPromoteOperationInputV2) {
      const prepared = prepareSessionRunInputOperationV2({ kind: 'promote', ...input });
      if (prepared.kind !== 'promote') throw sessionRunInputInputInvalidV2();
      return runDesktopSessionRunInputAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.promoteRunInput(
            prepared.runId,
            prepared.inputId,
            prepared.expectedSourceRunRevision,
            prepared.idempotencyKey,
            prepared.signal,
          ),
      );
    },
  });
}

export function withDesktopSessionRunInputAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopSessionRunInputOperationInputV2,
  operation: (
    authority: DesktopSessionRunInputAuthorityV2,
    prepared: PreparedSessionRunInputOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopSessionRunInputAuthorityOperationV2(
    actions,
    prepareSessionRunInputOperationV2(input),
    operation,
  );
}

async function runDesktopSessionRunInputAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedSessionRunInputOperationV2,
  operation: (
    authority: DesktopSessionRunInputAuthorityV2,
    prepared: PreparedSessionRunInputOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopSessionRunInputAuthorityServiceV2>({
      service: DESKTOP_SESSION_RUN_INPUT_AUTHORITY_SERVICE_V2,
      version: DESKTOP_SESSION_RUN_INPUT_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'session',
        tenant_id: prepared.identity.tenant_id,
        project_id: prepared.identity.project_id,
        session_id: prepared.identity.session_id,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopSessionRunInputAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireSessionRunInputServiceV2(candidate);
      const authority = requireSessionRunInputAuthorityV2(
        service.bindOperation(prepared.config, prepared.identity),
      );
      return operation(
        createRevocableSessionRunInputAuthorityV2(
          authority,
          prepared.identity,
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

function createDesktopSessionRunInputAuthorityV2(
  config: DesktopRuntimeConfig,
  identity: DesktopSessionRunInputIdentityV2,
): DesktopSessionRunInputAuthorityV2 {
  const operationConfig = cloneSessionRunInputRuntimeConfigV2(config);
  const operationIdentity = cloneSessionRunInputServiceIdentityV2(identity);
  assertSessionRunInputScopeV2(operationConfig, operationIdentity);
  const transport = new DesktopApiClient(operationConfig);
  return Object.freeze({
    createRunInput(
      runId: string,
      request: CreateRunInputRequest,
      signal?: AbortSignal,
    ) {
      const operationRunId = cloneSessionRunInputIdentifierV2(runId);
      const operationRequest = cloneSessionRunInputCreateRequestV2(request);
      const operationSignal = cloneSessionRunInputSignalV2(signal);
      return transport
        .createRunInput(operationRunId, operationRequest, operationSignal)
        .then((value) =>
          cloneSessionRunInputAckV2(
            value,
            operationIdentity,
            operationRunId,
            operationRequest,
          ),
        );
    },
    listRunInputs(runId: string, signal?: AbortSignal) {
      const operationRunId = cloneSessionRunInputIdentifierV2(runId);
      const operationSignal = cloneSessionRunInputSignalV2(signal);
      return transport
        .listRunInputs(operationRunId, operationSignal)
        .then((value) =>
          cloneSessionRunInputListResponseV2(
            value,
            operationIdentity,
            operationRunId,
          ),
        );
    },
    promoteRunInput(
      runId: string,
      inputId: string,
      expectedSourceRunRevision: number,
      idempotencyKey: string,
      signal?: AbortSignal,
    ) {
      const operationRunId = cloneSessionRunInputIdentifierV2(runId);
      const operationInputId = cloneSessionRunInputIdentifierV2(inputId);
      const operationRevision = cloneSessionRunInputRevisionV2(
        expectedSourceRunRevision,
      );
      const operationIdempotencyKey = cloneSessionRunInputIdentifierV2(idempotencyKey);
      const operationSignal = cloneSessionRunInputSignalV2(signal);
      return transport
        .promoteRunInput(
          operationRunId,
          operationInputId,
          operationRevision,
          operationIdempotencyKey,
          operationSignal,
        )
        .then((value) =>
          cloneSessionRunInputPromotionResponseV2(
            value,
            operationIdentity,
            operationRunId,
            operationInputId,
            operationRevision,
            operationIdempotencyKey,
          ),
        );
    },
  });
}

function createRevocableSessionRunInputAuthorityV2(
  authority: DesktopSessionRunInputAuthorityV2,
  identity: DesktopSessionRunInputIdentityV2,
  isOperationActive: () => boolean,
): DesktopSessionRunInputAuthorityV2 {
  return Object.freeze({
    createRunInput(
      runId: string,
      request: CreateRunInputRequest,
      signal?: AbortSignal,
    ) {
      assertOperationActiveV2(isOperationActive);
      const operationRunId = cloneSessionRunInputIdentifierV2(runId);
      const operationRequest = cloneSessionRunInputCreateRequestV2(request);
      const operationSignal = cloneSessionRunInputSignalV2(signal);
      return Promise.resolve(
        authority.createRunInput(operationRunId, operationRequest, operationSignal),
      ).then((value) =>
        cloneSessionRunInputAckV2(
          value,
          identity,
          operationRunId,
          operationRequest,
        ),
      );
    },
    listRunInputs(runId: string, signal?: AbortSignal) {
      assertOperationActiveV2(isOperationActive);
      const operationRunId = cloneSessionRunInputIdentifierV2(runId);
      const operationSignal = cloneSessionRunInputSignalV2(signal);
      return Promise.resolve(authority.listRunInputs(operationRunId, operationSignal)).then(
        (value) =>
          cloneSessionRunInputListResponseV2(value, identity, operationRunId),
      );
    },
    promoteRunInput(
      runId: string,
      inputId: string,
      expectedSourceRunRevision: number,
      idempotencyKey: string,
      signal?: AbortSignal,
    ) {
      assertOperationActiveV2(isOperationActive);
      const operationRunId = cloneSessionRunInputIdentifierV2(runId);
      const operationInputId = cloneSessionRunInputIdentifierV2(inputId);
      const operationRevision = cloneSessionRunInputRevisionV2(
        expectedSourceRunRevision,
      );
      const operationIdempotencyKey = cloneSessionRunInputIdentifierV2(idempotencyKey);
      const operationSignal = cloneSessionRunInputSignalV2(signal);
      return Promise.resolve(
        authority.promoteRunInput(
          operationRunId,
          operationInputId,
          operationRevision,
          operationIdempotencyKey,
          operationSignal,
        ),
      ).then((value) =>
        cloneSessionRunInputPromotionResponseV2(
          value,
          identity,
          operationRunId,
          operationInputId,
          operationRevision,
          operationIdempotencyKey,
        ),
      );
    },
  });
}

function prepareSessionRunInputOperationV2(
  input: DesktopSessionRunInputOperationInputV2,
): PreparedSessionRunInputOperationV2 {
  if (!isPlainRecordV2(input)) throw sessionRunInputInputInvalidV2();
  const keys =
    input.kind === 'create'
      ? CREATE_INPUT_KEYS_V2
      : input.kind === 'list'
        ? LIST_INPUT_KEYS_V2
        : input.kind === 'promote'
          ? PROMOTE_INPUT_KEYS_V2
          : null;
  if (keys === null || !hasOptionalExactKeysV2(input, keys)) {
    throw sessionRunInputInputInvalidV2();
  }
  const config = cloneSessionRunInputRuntimeConfigV2(input.config);
  const identity = cloneSessionRunInputIdentityV2(input.conversation);
  assertSessionRunInputScopeV2(config, identity);
  const runId = cloneSessionRunInputIdentifierV2(input.runId);
  const signal = cloneSessionRunInputSignalV2(input.signal);
  if (input.kind === 'create') {
    return Object.freeze({
      kind: 'create',
      config,
      identity,
      runId,
      request: cloneSessionRunInputCreateRequestV2(input.request),
      ...(signal === undefined ? {} : { signal }),
    });
  }
  if (input.kind === 'list') {
    return Object.freeze({
      kind: 'list',
      config,
      identity,
      runId,
      ...(signal === undefined ? {} : { signal }),
    });
  }
  return Object.freeze({
    kind: 'promote',
    config,
    identity,
    runId,
    inputId: cloneSessionRunInputIdentifierV2(input.inputId),
    expectedSourceRunRevision: cloneSessionRunInputRevisionV2(
      input.expectedSourceRunRevision,
    ),
    idempotencyKey: cloneSessionRunInputIdentifierV2(input.idempotencyKey),
    ...(signal === undefined ? {} : { signal }),
  });
}

function hasOptionalExactKeysV2(
  value: Record<string, unknown>,
  allowed: ReadonlySet<string>,
): boolean {
  return (
    Object.keys(value).every((key) => allowed.has(key)) &&
    [...allowed]
      .filter((key) => key !== 'signal')
      .every((key) => Object.hasOwn(value, key))
  );
}

function requireSessionRunInputServiceV2(
  value: unknown,
): DesktopSessionRunInputAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidSessionRunInputServiceV2();
  }
  return value as unknown as DesktopSessionRunInputAuthorityServiceV2;
}

function requireSessionRunInputAuthorityV2(
  value: unknown,
): DesktopSessionRunInputAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, AUTHORITY_KEYS_V2) ||
    typeof value.createRunInput !== 'function' ||
    typeof value.listRunInputs !== 'function' ||
    typeof value.promoteRunInput !== 'function'
  ) {
    throw invalidSessionRunInputServiceV2();
  }
  return value as unknown as DesktopSessionRunInputAuthorityV2;
}

function assertOperationActiveV2(isOperationActive: () => boolean): void {
  if (!isOperationActive()) {
    throw new RuntimeV2Error(
      'desktop_session_run_input_operation_released',
      'desktop session run-input operation has been released',
    );
  }
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopSessionRunInputAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function invalidSessionRunInputServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_session_run_input_service_invalid',
    'desktop session run-input authority service is invalid',
  );
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) =>
      candidate.module_ref === DESKTOP_SESSION_RUN_INPUT_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_session_run_input_authority_catalog_missing',
      'desktop session run-input authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
