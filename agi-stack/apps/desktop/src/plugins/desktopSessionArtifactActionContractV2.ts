import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  ArtifactDeliveryOutcome,
  ArtifactDeliveryRequest,
  ArtifactReviewOutcome,
  ArtifactReviewRequest,
  DesktopArtifactDelivery,
  DesktopArtifactVersion,
  DesktopRun,
  DesktopRuntimeConfig,
} from '../types';
import { cloneRuntimeConfigV2, isPlainRecordV2 } from './desktopNewTaskFlowContractV2';

export type DesktopSessionArtifactActionIdentityV2 = Readonly<{
  tenant_id: string;
  project_id: string;
  session_id: string;
}>;

export type DesktopArtifactReviewCommandV2 = Readonly<{
  artifactVersionId: string;
  input: ArtifactReviewRequest;
}>;

export type DesktopArtifactDeliveryCommandV2 = Readonly<{
  artifactVersionId: string;
  input: ArtifactDeliveryRequest;
}>;

const ARTIFACT_STATUSES_V2 = new Set(['draft', 'ready', 'approved', 'delivered', 'superseded']);
const RUN_STATUSES_V2 = new Set([
  'queued',
  'running',
  'needs_input',
  'needs_approval',
  'paused',
  'ready_review',
  'completed',
  'failed',
  'disconnected',
  'interrupted',
]);
const REVIEW_INPUT_KEYS_V2 = new Set([
  'action',
  'expectedRevision',
  'runExpectedRevision',
  'feedback',
]);
const DELIVERY_INPUT_KEYS_V2 = new Set(['expectedRevision', 'idempotencyKey', 'destination']);
const MAX_JSON_DEPTH_V2 = 32;

export function cloneSessionArtifactActionRuntimeConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  try {
    return cloneRuntimeConfigV2(config);
  } catch {
    throw sessionArtifactActionInputInvalidV2();
  }
}

export function cloneSessionArtifactActionIdentityV2(
  value: unknown,
): DesktopSessionArtifactActionIdentityV2 {
  if (
    !isPlainRecordV2(value) ||
    hasUnexpectedKeysV2(value, new Set(['tenant_id', 'project_id', 'session_id'])) ||
    !isCanonicalIdentifierV2(value.tenant_id) ||
    !isCanonicalIdentifierV2(value.project_id) ||
    !isCanonicalIdentifierV2(value.session_id)
  ) {
    throw sessionArtifactActionInputInvalidV2();
  }
  return Object.freeze({
    tenant_id: value.tenant_id,
    project_id: value.project_id,
    session_id: value.session_id,
  });
}

export function assertSessionArtifactActionScopeV2(
  config: DesktopRuntimeConfig,
  identity: DesktopSessionArtifactActionIdentityV2,
): void {
  if (config.tenantId !== identity.tenant_id || config.projectId !== identity.project_id) {
    throw new RuntimeV2Error(
      'desktop_session_artifact_action_scope_mismatch',
      'desktop session Artifact Action operation differs from its configured scope',
    );
  }
}

export function cloneArtifactReviewCommandV2(
  artifactVersionId: unknown,
  input: unknown,
): DesktopArtifactReviewCommandV2 {
  if (
    !isCanonicalIdentifierV2(artifactVersionId) ||
    !isPlainRecordV2(input) ||
    hasUnexpectedKeysV2(input, REVIEW_INPUT_KEYS_V2) ||
    !isRevisionV2(input.expectedRevision) ||
    (input.action !== 'approve' && input.action !== 'request_changes')
  ) {
    throw sessionArtifactActionInputInvalidV2();
  }
  if (input.action === 'approve') {
    if (input.runExpectedRevision !== undefined || input.feedback !== undefined) {
      throw sessionArtifactActionInputInvalidV2();
    }
    return Object.freeze({
      artifactVersionId,
      input: Object.freeze({
        action: 'approve',
        expectedRevision: input.expectedRevision,
      }),
    });
  }
  if (!isRevisionV2(input.runExpectedRevision) || !isCanonicalTextV2(input.feedback, 4_000)) {
    throw sessionArtifactActionInputInvalidV2();
  }
  return Object.freeze({
    artifactVersionId,
    input: Object.freeze({
      action: 'request_changes',
      expectedRevision: input.expectedRevision,
      runExpectedRevision: input.runExpectedRevision,
      feedback: input.feedback,
    }),
  });
}

export function cloneArtifactDeliveryCommandV2(
  artifactVersionId: unknown,
  input: unknown,
): DesktopArtifactDeliveryCommandV2 {
  if (
    !isCanonicalIdentifierV2(artifactVersionId) ||
    !isPlainRecordV2(input) ||
    hasUnexpectedKeysV2(input, DELIVERY_INPUT_KEYS_V2) ||
    !isRevisionV2(input.expectedRevision) ||
    !isIdempotencyKeyV2(input.idempotencyKey) ||
    (input.destination !== undefined && !isCanonicalTextV2(input.destination, 256))
  ) {
    throw sessionArtifactActionInputInvalidV2();
  }
  return Object.freeze({
    artifactVersionId,
    input: Object.freeze({
      expectedRevision: input.expectedRevision,
      idempotencyKey: input.idempotencyKey,
      ...(input.destination === undefined ? {} : { destination: input.destination }),
    }),
  });
}

export function assertArtifactReviewOutcomeV2(
  value: unknown,
  config: DesktopRuntimeConfig,
  identity: DesktopSessionArtifactActionIdentityV2,
  command: DesktopArtifactReviewCommandV2,
): ArtifactReviewOutcome {
  const expectedStatus = command.input.action === 'approve' ? 'approved' : 'changes_requested';
  const expectedArtifactStatus = command.input.action === 'approve' ? 'approved' : 'superseded';
  if (!isPlainRecordV2(value) || value.accepted !== true || value.status !== expectedStatus) {
    throw sessionArtifactActionResponseInvalidV2();
  }
  const artifactVersion = cloneArtifactVersionV2(value.artifact_version);
  assertArtifactResponseIdentityV2(
    artifactVersion,
    identity,
    command.artifactVersionId,
    command.input.expectedRevision,
    expectedArtifactStatus,
  );
  const outcomeRun = cloneOptionalRunV2(value.run, config, identity);
  const runExpectedRevision = command.input.runExpectedRevision;
  if (
    outcomeRun !== null &&
    (artifactVersion.run_id !== outcomeRun.id ||
      (command.input.action === 'request_changes' &&
        (typeof runExpectedRevision !== 'number' ||
          outcomeRun.revision !== runExpectedRevision + 1)))
  ) {
    throw sessionArtifactActionResponseInvalidV2();
  }
  return deepFreezeV2({
    accepted: true,
    status: expectedStatus,
    artifact_version: artifactVersion,
    ...(value.run === undefined ? {} : { run: outcomeRun }),
  }) as ArtifactReviewOutcome;
}

export function assertArtifactDeliveryOutcomeV2(
  value: unknown,
  identity: DesktopSessionArtifactActionIdentityV2,
  command: DesktopArtifactDeliveryCommandV2,
): ArtifactDeliveryOutcome {
  if (!isPlainRecordV2(value) || value.accepted !== true || value.status !== 'delivered') {
    throw sessionArtifactActionResponseInvalidV2();
  }
  const artifactVersion = cloneArtifactVersionV2(value.artifact_version);
  assertArtifactResponseIdentityV2(
    artifactVersion,
    identity,
    command.artifactVersionId,
    command.input.expectedRevision,
    'delivered',
  );
  const delivery = cloneArtifactDeliveryV2(value.delivery);
  const destination = command.input.destination ?? 'local_workspace';
  if (
    delivery.artifact_version_id !== command.artifactVersionId ||
    delivery.artifact_id !== artifactVersion.artifact_id ||
    delivery.conversation_id !== identity.session_id ||
    delivery.run_id !== artifactVersion.run_id ||
    delivery.destination !== destination ||
    delivery.idempotency_key !== command.input.idempotencyKey
  ) {
    throw sessionArtifactActionResponseInvalidV2();
  }
  return deepFreezeV2({
    accepted: true,
    status: 'delivered',
    artifact_version: artifactVersion,
    delivery,
  }) as ArtifactDeliveryOutcome;
}

export function sessionArtifactActionInputInvalidV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_session_artifact_action_input_invalid',
    'desktop session Artifact Action authority received invalid input',
  );
}

function sessionArtifactActionResponseInvalidV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_session_artifact_action_response_invalid',
    'desktop session Artifact Action authority returned an invalid response',
  );
}

function cloneArtifactVersionV2(value: unknown): DesktopArtifactVersion {
  if (
    !isPlainRecordV2(value) ||
    !isCanonicalIdentifierV2(value.id) ||
    !isCanonicalIdentifierV2(value.artifact_id) ||
    !isCanonicalIdentifierV2(value.source_artifact_id) ||
    !isCanonicalIdentifierV2(value.conversation_id) ||
    !isOptionalIdentifierV2(value.run_id) ||
    !isPositiveIntegerV2(value.version) ||
    !ARTIFACT_STATUSES_V2.has(String(value.status)) ||
    !isRevisionV2(value.revision) ||
    !isCanonicalTextV2(value.filename, 1_024) ||
    !isCanonicalTextV2(value.mime_type, 256) ||
    typeof value.path !== 'string' ||
    typeof value.relative_path !== 'string' ||
    !isNonNegativeIntegerV2(value.bytes) ||
    !Array.isArray(value.sources) ||
    !Array.isArray(value.checks) ||
    !isCanonicalTextV2(value.created_at, 256) ||
    !isCanonicalTextV2(value.updated_at, 256) ||
    !isOptionalTextV2(value.approved_at) ||
    !isOptionalTextV2(value.delivered_at) ||
    !isOptionalTextV2(value.superseded_at) ||
    !isOptionalTextV2(value.feedback)
  ) {
    throw sessionArtifactActionResponseInvalidV2();
  }
  return deepFreezeV2(cloneJsonValueV2(value, new Set<object>(), 0)) as DesktopArtifactVersion;
}

function cloneArtifactDeliveryV2(value: unknown): DesktopArtifactDelivery {
  if (
    !isPlainRecordV2(value) ||
    !isCanonicalIdentifierV2(value.id) ||
    !isCanonicalIdentifierV2(value.artifact_version_id) ||
    !isCanonicalIdentifierV2(value.artifact_id) ||
    !isCanonicalIdentifierV2(value.conversation_id) ||
    !isOptionalIdentifierV2(value.run_id) ||
    !isCanonicalTextV2(value.destination, 256) ||
    !Object.hasOwn(value, 'receipt') ||
    value.receipt === undefined ||
    !isIdempotencyKeyV2(value.idempotency_key) ||
    !isCanonicalTextV2(value.created_at, 256)
  ) {
    throw sessionArtifactActionResponseInvalidV2();
  }
  return deepFreezeV2(cloneJsonValueV2(value, new Set<object>(), 0)) as DesktopArtifactDelivery;
}

function cloneOptionalRunV2(
  value: unknown,
  config: DesktopRuntimeConfig,
  identity: DesktopSessionArtifactActionIdentityV2,
): DesktopRun | null {
  if (value === undefined || value === null) return null;
  if (
    !isPlainRecordV2(value) ||
    !isCanonicalIdentifierV2(value.id) ||
    value.conversation_id !== identity.session_id ||
    value.project_id !== config.projectId ||
    !isOptionalIdentifierV2(value.plan_version_id) ||
    !isCanonicalTextV2(value.idempotency_key, 256) ||
    !isCanonicalIdentifierV2(value.message_id) ||
    typeof value.request_message !== 'string' ||
    !RUN_STATUSES_V2.has(String(value.status)) ||
    !isRevisionV2(value.revision) ||
    !isCanonicalTextV2(value.created_at, 256) ||
    !isCanonicalTextV2(value.updated_at, 256) ||
    !isPlainRecordV2(value.authorization_snapshot)
  ) {
    throw sessionArtifactActionResponseInvalidV2();
  }
  return deepFreezeV2(cloneJsonValueV2(value, new Set<object>(), 0)) as DesktopRun;
}

function assertArtifactResponseIdentityV2(
  value: DesktopArtifactVersion,
  identity: DesktopSessionArtifactActionIdentityV2,
  artifactVersionId: string,
  expectedRevision: number,
  expectedStatus: string,
): void {
  if (
    value.id !== artifactVersionId ||
    value.conversation_id !== identity.session_id ||
    value.status !== expectedStatus ||
    (value.revision !== expectedRevision && value.revision !== expectedRevision + 1)
  ) {
    throw sessionArtifactActionResponseInvalidV2();
  }
}

function cloneJsonValueV2(value: unknown, ancestors: Set<object>, depth: number): unknown {
  if (depth > MAX_JSON_DEPTH_V2) {
    throw sessionArtifactActionResponseInvalidV2();
  }
  if (value === null || typeof value === 'string' || typeof value === 'boolean') {
    return value;
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw sessionArtifactActionResponseInvalidV2();
    return value;
  }
  if (
    typeof value !== 'object' ||
    value === null ||
    ancestors.has(value) ||
    (!Array.isArray(value) && !isPlainRecordV2(value))
  ) {
    throw sessionArtifactActionResponseInvalidV2();
  }
  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      return value.map((item) => cloneJsonValueV2(item, ancestors, depth + 1));
    }
    const copy: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) {
      if (item === undefined) throw sessionArtifactActionResponseInvalidV2();
      copy[key] = cloneJsonValueV2(item, ancestors, depth + 1);
    }
    return copy;
  } finally {
    ancestors.delete(value);
  }
}

function deepFreezeV2<T>(value: T): T {
  if (Array.isArray(value)) {
    for (const item of value) deepFreezeV2(item);
    return Object.freeze(value);
  }
  if (isPlainRecordV2(value)) {
    for (const item of Object.values(value)) deepFreezeV2(item);
    return Object.freeze(value) as T;
  }
  return value;
}

function hasUnexpectedKeysV2(
  value: Record<string, unknown>,
  allowed: ReadonlySet<string>,
): boolean {
  return Object.keys(value).some((key) => !allowed.has(key));
}

function isRevisionV2(value: unknown): value is number {
  return (
    Number.isSafeInteger(value) && Number(value) >= 0 && Number(value) < Number.MAX_SAFE_INTEGER
  );
}

function isPositiveIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

function isNonNegativeIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function isCanonicalIdentifierV2(value: unknown): value is string {
  return (
    typeof value === 'string' && value.length > 0 && value.length <= 256 && value === value.trim()
  );
}

function isCanonicalTextV2(value: unknown, maximumLength: number): value is string {
  return (
    typeof value === 'string' &&
    value.length > 0 &&
    value.length <= maximumLength &&
    value === value.trim()
  );
}

function isOptionalIdentifierV2(value: unknown): boolean {
  return value === null || isCanonicalIdentifierV2(value);
}

function isOptionalTextV2(value: unknown): boolean {
  return value === null || isCanonicalTextV2(value, 4_000);
}

function isIdempotencyKeyV2(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length >= 8 &&
    value.length <= 128 &&
    value === value.trim() &&
    [...value].every((character) => {
      const code = character.charCodeAt(0);
      return code >= 33 && code <= 126;
    })
  );
}
