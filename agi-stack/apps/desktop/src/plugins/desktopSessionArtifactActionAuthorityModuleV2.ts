import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import { DesktopApiClient } from '../api/client';
import type {
  ArtifactDeliveryOutcome,
  ArtifactDeliveryRequest,
  ArtifactReviewOutcome,
  ArtifactReviewRequest,
  DesktopRuntimeConfig,
} from '../types';
import {
  assertArtifactDeliveryOutcomeV2,
  assertArtifactReviewOutcomeV2,
  assertSessionArtifactActionScopeV2,
  cloneArtifactDeliveryCommandV2,
  cloneArtifactReviewCommandV2,
  cloneSessionArtifactActionIdentityV2,
  cloneSessionArtifactActionRuntimeConfigV2,
  sessionArtifactActionInputInvalidV2,
  type DesktopArtifactDeliveryCommandV2,
  type DesktopArtifactReviewCommandV2,
  type DesktopSessionArtifactActionIdentityV2,
} from './desktopSessionArtifactActionContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/session-artifact-action-authority';
export const DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.session-artifact-action-authority';
export const DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopSessionArtifactActionClientV2 {
  readonly reviewArtifactVersion: (
    artifactVersionId: string,
    input: ArtifactReviewRequest,
  ) => Promise<ArtifactReviewOutcome>;
  readonly deliverArtifactVersion: (
    artifactVersionId: string,
    input: ArtifactDeliveryRequest,
  ) => Promise<ArtifactDeliveryOutcome>;
}

export interface DesktopSessionArtifactActionAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    identity: DesktopSessionArtifactActionIdentityV2,
  ) => DesktopSessionArtifactActionClientV2;
}

export interface DesktopSessionArtifactActionOperationsV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    conversationId: string,
  ) => DesktopSessionArtifactActionClientV2;
}

export type DesktopSessionArtifactActionOperationInputV2 =
  | Readonly<{
      kind: 'review';
      config: DesktopRuntimeConfig;
      conversationId: string;
      artifactVersionId: string;
      input: ArtifactReviewRequest;
    }>
  | Readonly<{
      kind: 'deliver';
      config: DesktopRuntimeConfig;
      conversationId: string;
      artifactVersionId: string;
      input: ArtifactDeliveryRequest;
    }>;

type PreparedSessionArtifactActionOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  identity: DesktopSessionArtifactActionIdentityV2;
}> &
  (
    | Readonly<{
        kind: 'review';
        command: DesktopArtifactReviewCommandV2;
      }>
    | Readonly<{
        kind: 'deliver';
        command: DesktopArtifactDeliveryCommandV2;
      }>
  );

type ServiceAdmissionRejectionV2 = Extract<
  DesktopRendererServiceOperationLeaseAdmissionV2<never>,
  { status: 'rejected' }
>;
type GenerationActionsUnavailableV2 = Readonly<{
  reasonCode: 'desktop_renderer_generation_actions_unavailable';
  runtimeCode?: undefined;
}>;
type AuthorityAdmissionRejectionV2 = ServiceAdmissionRejectionV2 | GenerationActionsUnavailableV2;

const AUTHORITY_METHODS_V2 = new Set(['reviewArtifactVersion', 'deliverArtifactVersion']);

export class DesktopSessionArtifactActionAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopSessionArtifactActionAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopSessionArtifactActionAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_session_artifact_action_authority_config_invalid',
      'desktop session Artifact Action authority requires desktop-api-client strategy',
    );
  }
  const service: DesktopSessionArtifactActionAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopSessionArtifactActionAuthorityV2,
  });
  context.provide(DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_SERVICE_V2, service);
}

export const desktopSessionArtifactActionAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopSessionArtifactActionAuthorityV2,
});

export function createDesktopSessionArtifactActionOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopSessionArtifactActionOperationsV2 {
  return Object.freeze({
    bindOperation(config: DesktopRuntimeConfig, conversationId: string) {
      const operationConfig = cloneSessionArtifactActionRuntimeConfigV2(config);
      const identity = cloneSessionArtifactActionIdentityV2({
        tenant_id: operationConfig.tenantId,
        project_id: operationConfig.projectId,
        session_id: conversationId,
      });
      assertSessionArtifactActionScopeV2(operationConfig, identity);
      return createGenerationBoundClientV2(resolveActions, operationConfig, identity);
    },
  });
}

export function withDesktopSessionArtifactActionAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopSessionArtifactActionOperationInputV2,
  operation: (
    authority: DesktopSessionArtifactActionClientV2,
    prepared: PreparedSessionArtifactActionOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runSessionArtifactActionOperationV2(
    actions,
    prepareSessionArtifactActionOperationV2(input),
    operation,
  );
}

function createGenerationBoundClientV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
  config: DesktopRuntimeConfig,
  identity: DesktopSessionArtifactActionIdentityV2,
): DesktopSessionArtifactActionClientV2 {
  return Object.freeze({
    async reviewArtifactVersion(artifactVersionId: string, input: ArtifactReviewRequest) {
      const prepared = prepareSessionArtifactActionOperationV2({
        kind: 'review',
        config,
        conversationId: identity.session_id,
        artifactVersionId,
        input,
      });
      if (prepared.kind !== 'review') throw sessionArtifactActionInputInvalidV2();
      return await runSessionArtifactActionOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.reviewArtifactVersion(
            prepared.command.artifactVersionId,
            prepared.command.input,
          ),
      );
    },
    async deliverArtifactVersion(artifactVersionId: string, input: ArtifactDeliveryRequest) {
      const prepared = prepareSessionArtifactActionOperationV2({
        kind: 'deliver',
        config,
        conversationId: identity.session_id,
        artifactVersionId,
        input,
      });
      if (prepared.kind !== 'deliver') throw sessionArtifactActionInputInvalidV2();
      return await runSessionArtifactActionOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.deliverArtifactVersion(
            prepared.command.artifactVersionId,
            prepared.command.input,
          ),
      );
    },
  });
}

async function runSessionArtifactActionOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedSessionArtifactActionOperationV2,
  operation: (
    authority: DesktopSessionArtifactActionClientV2,
    prepared: PreparedSessionArtifactActionOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopSessionArtifactActionAuthorityServiceV2>({
      service: DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_SERVICE_V2,
      version: DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'session',
        tenant_id: prepared.identity.tenant_id,
        project_id: prepared.identity.project_id,
        session_id: prepared.identity.session_id,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopSessionArtifactActionAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireSessionArtifactActionServiceV2(candidate);
      const authority = requireSessionArtifactActionAuthorityV2(
        service.bindOperation(prepared.config, prepared.identity),
      );
      return operation(
        createRevocableSessionArtifactActionAuthorityV2(authority, prepared, () => operationActive),
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

function createDesktopSessionArtifactActionAuthorityV2(
  config: DesktopRuntimeConfig,
  identity: DesktopSessionArtifactActionIdentityV2,
): DesktopSessionArtifactActionClientV2 {
  const operationConfig = cloneSessionArtifactActionRuntimeConfigV2(config);
  const operationIdentity = cloneSessionArtifactActionIdentityV2(identity);
  assertSessionArtifactActionScopeV2(operationConfig, operationIdentity);
  const client = new DesktopApiClient(operationConfig);
  return Object.freeze({
    async reviewArtifactVersion(artifactVersionId: string, input: ArtifactReviewRequest) {
      const command = cloneArtifactReviewCommandV2(artifactVersionId, input);
      const response = await client.reviewArtifactVersion(command.artifactVersionId, command.input);
      return assertArtifactReviewOutcomeV2(response, operationConfig, operationIdentity, command);
    },
    async deliverArtifactVersion(artifactVersionId: string, input: ArtifactDeliveryRequest) {
      const command = cloneArtifactDeliveryCommandV2(artifactVersionId, input);
      const response = await client.deliverArtifactVersion(
        command.artifactVersionId,
        command.input,
      );
      return assertArtifactDeliveryOutcomeV2(response, operationIdentity, command);
    },
  });
}

function createRevocableSessionArtifactActionAuthorityV2(
  authority: DesktopSessionArtifactActionClientV2,
  prepared: PreparedSessionArtifactActionOperationV2,
  isOperationActive: () => boolean,
): DesktopSessionArtifactActionClientV2 {
  return Object.freeze({
    async reviewArtifactVersion(artifactVersionId: string, input: ArtifactReviewRequest) {
      requireActiveOperationV2(isOperationActive);
      if (prepared.kind !== 'review') throw sessionArtifactActionInputInvalidV2();
      const command = cloneArtifactReviewCommandV2(artifactVersionId, input);
      assertSameReviewCommandV2(command, prepared.command);
      const response = await authority.reviewArtifactVersion(
        command.artifactVersionId,
        command.input,
      );
      return assertArtifactReviewOutcomeV2(response, prepared.config, prepared.identity, command);
    },
    async deliverArtifactVersion(artifactVersionId: string, input: ArtifactDeliveryRequest) {
      requireActiveOperationV2(isOperationActive);
      if (prepared.kind !== 'deliver') throw sessionArtifactActionInputInvalidV2();
      const command = cloneArtifactDeliveryCommandV2(artifactVersionId, input);
      assertSameDeliveryCommandV2(command, prepared.command);
      const response = await authority.deliverArtifactVersion(
        command.artifactVersionId,
        command.input,
      );
      return assertArtifactDeliveryOutcomeV2(response, prepared.identity, command);
    },
  });
}

function prepareSessionArtifactActionOperationV2(
  input: DesktopSessionArtifactActionOperationInputV2,
): PreparedSessionArtifactActionOperationV2 {
  if (!isPlainRecordV2(input)) throw sessionArtifactActionInputInvalidV2();
  const config = cloneSessionArtifactActionRuntimeConfigV2(input.config);
  const identity = cloneSessionArtifactActionIdentityV2({
    tenant_id: config.tenantId,
    project_id: config.projectId,
    session_id: input.conversationId,
  });
  assertSessionArtifactActionScopeV2(config, identity);
  if (input.kind === 'review') {
    return Object.freeze({
      kind: 'review',
      config,
      identity,
      command: cloneArtifactReviewCommandV2(input.artifactVersionId, input.input),
    });
  }
  if (input.kind === 'deliver') {
    return Object.freeze({
      kind: 'deliver',
      config,
      identity,
      command: cloneArtifactDeliveryCommandV2(input.artifactVersionId, input.input),
    });
  }
  throw sessionArtifactActionInputInvalidV2();
}

function requireSessionArtifactActionServiceV2(
  value: unknown,
): DesktopSessionArtifactActionAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).some((key) => key !== 'bindOperation') ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidSessionArtifactActionServiceV2();
  }
  return value as unknown as DesktopSessionArtifactActionAuthorityServiceV2;
}

function requireSessionArtifactActionAuthorityV2(
  value: unknown,
): DesktopSessionArtifactActionClientV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).some((key) => !AUTHORITY_METHODS_V2.has(key)) ||
    Object.keys(value).length !== AUTHORITY_METHODS_V2.size ||
    typeof value.reviewArtifactVersion !== 'function' ||
    typeof value.deliverArtifactVersion !== 'function'
  ) {
    throw invalidSessionArtifactActionServiceV2();
  }
  return value as unknown as DesktopSessionArtifactActionClientV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null && typeof actions.acquireServiceOperationLease === 'function') {
    return actions;
  }
  throw new DesktopSessionArtifactActionAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireActiveOperationV2(isOperationActive: () => boolean): void {
  if (!isOperationActive()) {
    throw new RuntimeV2Error(
      'desktop_session_artifact_action_operation_released',
      'desktop session Artifact Action operation has been released',
    );
  }
}

function assertSameReviewCommandV2(
  actual: DesktopArtifactReviewCommandV2,
  expected: DesktopArtifactReviewCommandV2,
): void {
  if (
    actual.artifactVersionId !== expected.artifactVersionId ||
    actual.input.action !== expected.input.action ||
    actual.input.expectedRevision !== expected.input.expectedRevision ||
    actual.input.runExpectedRevision !== expected.input.runExpectedRevision ||
    actual.input.feedback !== expected.input.feedback
  ) {
    throw sessionArtifactActionInputInvalidV2();
  }
}

function assertSameDeliveryCommandV2(
  actual: DesktopArtifactDeliveryCommandV2,
  expected: DesktopArtifactDeliveryCommandV2,
): void {
  if (
    actual.artifactVersionId !== expected.artifactVersionId ||
    actual.input.expectedRevision !== expected.input.expectedRevision ||
    actual.input.idempotencyKey !== expected.input.idempotencyKey ||
    actual.input.destination !== expected.input.destination
  ) {
    throw sessionArtifactActionInputInvalidV2();
  }
}

function invalidSessionArtifactActionServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_session_artifact_action_service_invalid',
    'desktop session Artifact Action authority service is invalid',
  );
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === DESKTOP_SESSION_ARTIFACT_ACTION_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_session_artifact_action_authority_catalog_missing',
      'desktop session Artifact Action authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
