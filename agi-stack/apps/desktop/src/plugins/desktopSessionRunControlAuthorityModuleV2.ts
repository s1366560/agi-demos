import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import { DesktopApiClient } from '../api/client';
import type {
  DesktopRuntimeConfig,
  ForkRecoveryOutcome,
  ReviewRunRequest,
  RunControlOutcome,
} from '../types';
import {
  assertForkRecoveryOutcomeV2,
  assertRunControlOutcomeV2,
  assertSessionRunControlScopeV2,
  cloneRunForkCommandV2,
  cloneRunReviewCommandV2,
  cloneRunTransitionCommandV2,
  cloneSessionRunControlIdentityV2,
  cloneSessionRunControlRuntimeConfigV2,
  sessionRunControlInputInvalidV2,
  type DesktopRunControlCommandV2,
  type DesktopRunForkCommandV2,
  type DesktopRunReviewCommandV2,
  type DesktopRunTransitionCommandV2,
  type DesktopRunTransitionKindV2,
  type DesktopSessionRunControlIdentityV2,
} from './desktopSessionRunControlContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/session-run-control-authority';
export const DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.session-run-control-authority';
export const DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopSessionRunControlClientV2 {
  readonly pauseRun: (runId: string, expectedRevision: number) => Promise<RunControlOutcome>;
  readonly resumeRun: (runId: string, expectedRevision: number) => Promise<RunControlOutcome>;
  readonly forkRecoveryRun: (
    runId: string,
    expectedRevision: number,
    idempotencyKey: string,
  ) => Promise<ForkRecoveryOutcome>;
  readonly cancelRun: (runId: string, expectedRevision: number) => Promise<RunControlOutcome>;
  readonly reviewRun: (runId: string, input: ReviewRunRequest) => Promise<RunControlOutcome>;
}

export interface DesktopSessionRunControlAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    identity: DesktopSessionRunControlIdentityV2,
  ) => DesktopSessionRunControlClientV2;
}

export interface DesktopSessionRunControlOperationsV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    conversationId: string,
  ) => DesktopSessionRunControlClientV2;
}

export type DesktopSessionRunControlOperationInputV2 =
  | Readonly<{
      kind: DesktopRunTransitionKindV2;
      config: DesktopRuntimeConfig;
      conversationId: string;
      runId: string;
      expectedRevision: number;
    }>
  | Readonly<{
      kind: 'fork';
      config: DesktopRuntimeConfig;
      conversationId: string;
      runId: string;
      expectedRevision: number;
      idempotencyKey: string;
    }>
  | Readonly<{
      kind: 'review';
      config: DesktopRuntimeConfig;
      conversationId: string;
      runId: string;
      input: ReviewRunRequest;
    }>;

type PreparedSessionRunControlOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  identity: DesktopSessionRunControlIdentityV2;
  command: DesktopRunControlCommandV2;
}>;

type ServiceAdmissionRejectionV2 = Extract<
  DesktopRendererServiceOperationLeaseAdmissionV2<never>,
  { status: 'rejected' }
>;
type GenerationActionsUnavailableV2 = Readonly<{
  reasonCode: 'desktop_renderer_generation_actions_unavailable';
  runtimeCode?: undefined;
}>;
type AuthorityAdmissionRejectionV2 = ServiceAdmissionRejectionV2 | GenerationActionsUnavailableV2;

const AUTHORITY_METHODS_V2 = new Set([
  'pauseRun',
  'resumeRun',
  'forkRecoveryRun',
  'cancelRun',
  'reviewRun',
]);

export class DesktopSessionRunControlAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopSessionRunControlAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopSessionRunControlAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_session_run_control_authority_config_invalid',
      'desktop session run-control authority requires desktop-api-client strategy',
    );
  }
  const service: DesktopSessionRunControlAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopSessionRunControlAuthorityV2,
  });
  context.provide(DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_SERVICE_V2, service);
}

export const desktopSessionRunControlAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopSessionRunControlAuthorityV2,
});

export function createDesktopSessionRunControlOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopSessionRunControlOperationsV2 {
  return Object.freeze({
    bindOperation(config: DesktopRuntimeConfig, conversationId: string) {
      const operationConfig = cloneSessionRunControlRuntimeConfigV2(config);
      const identity = cloneSessionRunControlIdentityV2({
        tenant_id: operationConfig.tenantId,
        project_id: operationConfig.projectId,
        session_id: conversationId,
      });
      assertSessionRunControlScopeV2(operationConfig, identity);
      return createGenerationBoundClientV2(resolveActions, operationConfig, identity);
    },
  });
}

export function withDesktopSessionRunControlAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopSessionRunControlOperationInputV2,
  operation: (
    authority: DesktopSessionRunControlClientV2,
    prepared: PreparedSessionRunControlOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runSessionRunControlOperationV2(
    actions,
    prepareSessionRunControlOperationV2(input),
    operation,
  );
}

function createGenerationBoundClientV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
  config: DesktopRuntimeConfig,
  identity: DesktopSessionRunControlIdentityV2,
): DesktopSessionRunControlClientV2 {
  return Object.freeze({
    async pauseRun(runId: string, expectedRevision: number) {
      return await runTransitionV2(
        resolveActions,
        config,
        identity,
        'pause',
        runId,
        expectedRevision,
      );
    },
    async resumeRun(runId: string, expectedRevision: number) {
      return await runTransitionV2(
        resolveActions,
        config,
        identity,
        'resume',
        runId,
        expectedRevision,
      );
    },
    async forkRecoveryRun(runId: string, expectedRevision: number, idempotencyKey: string) {
      const prepared = prepareSessionRunControlOperationV2({
        kind: 'fork',
        config,
        conversationId: identity.session_id,
        runId,
        expectedRevision,
        idempotencyKey,
      });
      if (prepared.command.kind !== 'fork') throw sessionRunControlInputInvalidV2();
      const command = prepared.command;
      return await runSessionRunControlOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.forkRecoveryRun(
            command.runId,
            command.expectedRevision,
            command.idempotencyKey,
          ),
      );
    },
    async cancelRun(runId: string, expectedRevision: number) {
      return await runTransitionV2(
        resolveActions,
        config,
        identity,
        'cancel',
        runId,
        expectedRevision,
      );
    },
    async reviewRun(runId: string, input: ReviewRunRequest) {
      const prepared = prepareSessionRunControlOperationV2({
        kind: 'review',
        config,
        conversationId: identity.session_id,
        runId,
        input,
      });
      if (prepared.command.kind !== 'review') throw sessionRunControlInputInvalidV2();
      const command = prepared.command;
      return await runSessionRunControlOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.reviewRun(command.runId, command.input),
      );
    },
  });
}

async function runTransitionV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
  config: DesktopRuntimeConfig,
  identity: DesktopSessionRunControlIdentityV2,
  kind: DesktopRunTransitionKindV2,
  runId: string,
  expectedRevision: number,
): Promise<RunControlOutcome> {
  const prepared = prepareSessionRunControlOperationV2({
    kind,
    config,
    conversationId: identity.session_id,
    runId,
    expectedRevision,
  });
  if (!isRunTransitionCommandV2(prepared.command) || prepared.command.kind !== kind) {
    throw sessionRunControlInputInvalidV2();
  }
  const command = prepared.command;
  return await runSessionRunControlOperationV2(
    requireGenerationActionsV2(resolveActions()),
    prepared,
    (authority) =>
      authority[
        kind === 'pause' ? 'pauseRun' : kind === 'resume' ? 'resumeRun' : 'cancelRun'
      ](command.runId, command.expectedRevision),
  );
}

async function runSessionRunControlOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedSessionRunControlOperationV2,
  operation: (
    authority: DesktopSessionRunControlClientV2,
    prepared: PreparedSessionRunControlOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopSessionRunControlAuthorityServiceV2>({
      service: DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_SERVICE_V2,
      version: DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'session',
        tenant_id: prepared.identity.tenant_id,
        project_id: prepared.identity.project_id,
        session_id: prepared.identity.session_id,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopSessionRunControlAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireSessionRunControlServiceV2(candidate);
      const authority = requireSessionRunControlAuthorityV2(
        service.bindOperation(prepared.config, prepared.identity),
      );
      return operation(
        createRevocableSessionRunControlAuthorityV2(authority, prepared, () => operationActive),
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

function createDesktopSessionRunControlAuthorityV2(
  config: DesktopRuntimeConfig,
  identity: DesktopSessionRunControlIdentityV2,
): DesktopSessionRunControlClientV2 {
  const operationConfig = cloneSessionRunControlRuntimeConfigV2(config);
  const operationIdentity = cloneSessionRunControlIdentityV2(identity);
  assertSessionRunControlScopeV2(operationConfig, operationIdentity);
  const client = new DesktopApiClient(operationConfig);
  return Object.freeze({
    async pauseRun(runId: string, expectedRevision: number) {
      const command = cloneRunTransitionCommandV2('pause', runId, expectedRevision);
      const response = await client.pauseRun(command.runId, command.expectedRevision);
      return assertRunControlOutcomeV2(response, operationConfig, operationIdentity, command);
    },
    async resumeRun(runId: string, expectedRevision: number) {
      const command = cloneRunTransitionCommandV2('resume', runId, expectedRevision);
      const response = await client.resumeRun(command.runId, command.expectedRevision);
      return assertRunControlOutcomeV2(response, operationConfig, operationIdentity, command);
    },
    async forkRecoveryRun(runId: string, expectedRevision: number, idempotencyKey: string) {
      const command = cloneRunForkCommandV2(runId, expectedRevision, idempotencyKey);
      const response = await client.forkRecoveryRun(
        command.runId,
        command.expectedRevision,
        command.idempotencyKey,
      );
      return assertForkRecoveryOutcomeV2(response, operationConfig, operationIdentity, command);
    },
    async cancelRun(runId: string, expectedRevision: number) {
      const command = cloneRunTransitionCommandV2('cancel', runId, expectedRevision);
      const response = await client.cancelRun(command.runId, command.expectedRevision);
      return assertRunControlOutcomeV2(response, operationConfig, operationIdentity, command);
    },
    async reviewRun(runId: string, input: ReviewRunRequest) {
      const command = cloneRunReviewCommandV2(runId, input);
      const response = await client.reviewRun(command.runId, command.input);
      return assertRunControlOutcomeV2(response, operationConfig, operationIdentity, command);
    },
  });
}

function createRevocableSessionRunControlAuthorityV2(
  authority: DesktopSessionRunControlClientV2,
  prepared: PreparedSessionRunControlOperationV2,
  isOperationActive: () => boolean,
): DesktopSessionRunControlClientV2 {
  return Object.freeze({
    async pauseRun(runId: string, expectedRevision: number) {
      const command = requirePreparedTransitionV2(prepared, 'pause', runId, expectedRevision);
      requireActiveOperationV2(isOperationActive);
      const response = await authority.pauseRun(command.runId, command.expectedRevision);
      return assertRunControlOutcomeV2(response, prepared.config, prepared.identity, command);
    },
    async resumeRun(runId: string, expectedRevision: number) {
      const command = requirePreparedTransitionV2(prepared, 'resume', runId, expectedRevision);
      requireActiveOperationV2(isOperationActive);
      const response = await authority.resumeRun(command.runId, command.expectedRevision);
      return assertRunControlOutcomeV2(response, prepared.config, prepared.identity, command);
    },
    async forkRecoveryRun(runId: string, expectedRevision: number, idempotencyKey: string) {
      requireActiveOperationV2(isOperationActive);
      const command = cloneRunForkCommandV2(runId, expectedRevision, idempotencyKey);
      if (prepared.command.kind !== 'fork') throw sessionRunControlInputInvalidV2();
      assertSameForkCommandV2(command, prepared.command);
      const response = await authority.forkRecoveryRun(
        command.runId,
        command.expectedRevision,
        command.idempotencyKey,
      );
      return assertForkRecoveryOutcomeV2(response, prepared.config, prepared.identity, command);
    },
    async cancelRun(runId: string, expectedRevision: number) {
      const command = requirePreparedTransitionV2(prepared, 'cancel', runId, expectedRevision);
      requireActiveOperationV2(isOperationActive);
      const response = await authority.cancelRun(command.runId, command.expectedRevision);
      return assertRunControlOutcomeV2(response, prepared.config, prepared.identity, command);
    },
    async reviewRun(runId: string, input: ReviewRunRequest) {
      requireActiveOperationV2(isOperationActive);
      const command = cloneRunReviewCommandV2(runId, input);
      if (prepared.command.kind !== 'review') throw sessionRunControlInputInvalidV2();
      assertSameReviewCommandV2(command, prepared.command);
      const response = await authority.reviewRun(command.runId, command.input);
      return assertRunControlOutcomeV2(response, prepared.config, prepared.identity, command);
    },
  });
}

function prepareSessionRunControlOperationV2(
  input: DesktopSessionRunControlOperationInputV2,
): PreparedSessionRunControlOperationV2 {
  if (!isPlainRecordV2(input)) throw sessionRunControlInputInvalidV2();
  const config = cloneSessionRunControlRuntimeConfigV2(input.config);
  const identity = cloneSessionRunControlIdentityV2({
    tenant_id: config.tenantId,
    project_id: config.projectId,
    session_id: input.conversationId,
  });
  assertSessionRunControlScopeV2(config, identity);
  if (input.kind === 'pause' || input.kind === 'resume' || input.kind === 'cancel') {
    return Object.freeze({
      config,
      identity,
      command: cloneRunTransitionCommandV2(input.kind, input.runId, input.expectedRevision),
    });
  }
  if (input.kind === 'fork') {
    return Object.freeze({
      config,
      identity,
      command: cloneRunForkCommandV2(input.runId, input.expectedRevision, input.idempotencyKey),
    });
  }
  if (input.kind === 'review') {
    return Object.freeze({
      config,
      identity,
      command: cloneRunReviewCommandV2(input.runId, input.input),
    });
  }
  throw sessionRunControlInputInvalidV2();
}

function requirePreparedTransitionV2(
  prepared: PreparedSessionRunControlOperationV2,
  kind: DesktopRunTransitionKindV2,
  runId: string,
  expectedRevision: number,
): DesktopRunTransitionCommandV2 {
  const command = cloneRunTransitionCommandV2(kind, runId, expectedRevision);
  if (!isRunTransitionCommandV2(prepared.command) || prepared.command.kind !== kind) {
    throw sessionRunControlInputInvalidV2();
  }
  assertSameTransitionCommandV2(command, prepared.command);
  return command;
}

function isRunTransitionCommandV2(
  command: DesktopRunControlCommandV2,
): command is DesktopRunTransitionCommandV2 {
  return command.kind === 'pause' || command.kind === 'resume' || command.kind === 'cancel';
}

function requireSessionRunControlServiceV2(
  value: unknown,
): DesktopSessionRunControlAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).some((key) => key !== 'bindOperation') ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidSessionRunControlServiceV2();
  }
  return value as unknown as DesktopSessionRunControlAuthorityServiceV2;
}

function requireSessionRunControlAuthorityV2(value: unknown): DesktopSessionRunControlClientV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).some((key) => !AUTHORITY_METHODS_V2.has(key)) ||
    Object.keys(value).length !== AUTHORITY_METHODS_V2.size ||
    typeof value.pauseRun !== 'function' ||
    typeof value.resumeRun !== 'function' ||
    typeof value.forkRecoveryRun !== 'function' ||
    typeof value.cancelRun !== 'function' ||
    typeof value.reviewRun !== 'function'
  ) {
    throw invalidSessionRunControlServiceV2();
  }
  return value as unknown as DesktopSessionRunControlClientV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null && typeof actions.acquireServiceOperationLease === 'function') {
    return actions;
  }
  throw new DesktopSessionRunControlAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireActiveOperationV2(isOperationActive: () => boolean): void {
  if (!isOperationActive()) {
    throw new RuntimeV2Error(
      'desktop_session_run_control_operation_released',
      'desktop session run-control operation has been released',
    );
  }
}

function assertSameTransitionCommandV2(
  actual: DesktopRunTransitionCommandV2,
  expected: DesktopRunTransitionCommandV2,
): void {
  if (
    actual.kind !== expected.kind ||
    actual.runId !== expected.runId ||
    actual.expectedRevision !== expected.expectedRevision
  ) {
    throw sessionRunControlInputInvalidV2();
  }
}

function assertSameForkCommandV2(
  actual: DesktopRunForkCommandV2,
  expected: DesktopRunForkCommandV2,
): void {
  if (
    actual.runId !== expected.runId ||
    actual.expectedRevision !== expected.expectedRevision ||
    actual.idempotencyKey !== expected.idempotencyKey
  ) {
    throw sessionRunControlInputInvalidV2();
  }
}

function assertSameReviewCommandV2(
  actual: DesktopRunReviewCommandV2,
  expected: DesktopRunReviewCommandV2,
): void {
  if (
    actual.runId !== expected.runId ||
    actual.input.action !== expected.input.action ||
    actual.input.expectedRevision !== expected.input.expectedRevision ||
    actual.input.feedback !== expected.input.feedback
  ) {
    throw sessionRunControlInputInvalidV2();
  }
}

function invalidSessionRunControlServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_session_run_control_service_invalid',
    'desktop session run-control authority service is invalid',
  );
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === DESKTOP_SESSION_RUN_CONTROL_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_session_run_control_authority_catalog_missing',
      'desktop session run-control authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
