import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type { DesktopRuntimeConfig } from '../types';
import { readArtifactContentContractV2 } from '../features/chat/artifactContentContractV2';
import {
  createHttpDesktopArtifactClient,
  DesktopArtifactRequestError,
  type ArtifactContentContractV2,
  type ArtifactSaveCommandV2,
  type ArtifactSaveReceipt,
  type DesktopArtifactClient,
} from '../features/chat/desktopArtifactClient';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_ARTIFACT_CONTENT_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/artifact-content-authority';
export const DESKTOP_ARTIFACT_CONTENT_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.artifact-content-authority';
export const DESKTOP_ARTIFACT_CONTENT_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopArtifactContentAuthorityServiceV2 {
  readonly bindOperation: (config: DesktopRuntimeConfig) => DesktopArtifactClient;
}

export type DesktopArtifactContentOperationInputV2 =
  | Readonly<{
      kind: 'download' | 'load';
      config: DesktopRuntimeConfig;
      artifactId: string;
      signal?: AbortSignal;
    }>
  | Readonly<{
      kind: 'save';
      config: DesktopRuntimeConfig;
      artifactId: string;
      command: ArtifactSaveCommandV2;
      signal?: AbortSignal;
    }>;

type PreparedArtifactContentOperationV2 =
  | Readonly<{
      kind: 'download' | 'load';
      config: DesktopRuntimeConfig;
      artifactId: string;
      signal?: AbortSignal;
    }>
  | Readonly<{
      kind: 'save';
      config: DesktopRuntimeConfig;
      artifactId: string;
      command: ArtifactSaveCommandV2;
      signal?: AbortSignal;
    }>;

type PreparedArtifactContentSaveOperationV2 = Extract<
  PreparedArtifactContentOperationV2,
  { kind: 'save' }
>;

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

const SHA256_CONTENT_HASH_PATTERN_V2 = /^sha256:[a-f0-9]{64}$/u;
const IDEMPOTENCY_KEY_PATTERN_V2 = /^[A-Za-z0-9._:-]{8,128}$/u;

export class DesktopArtifactContentAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: string;
  readonly runtimeCode: string | undefined;

  constructor(
    rejection:
      | AuthorityAdmissionRejectionV2
      | Readonly<{ reasonCode: string; runtimeCode?: string }>,
  ) {
    super(rejection.reasonCode);
    this.name = 'DesktopArtifactContentAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopArtifactContentAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_artifact_content_authority_config_invalid',
      'desktop artifact content authority requires desktop-api-fetch strategy',
    );
  }
  const service: DesktopArtifactContentAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopArtifactContentAuthorityV2,
  });
  context.provide(DESKTOP_ARTIFACT_CONTENT_AUTHORITY_SERVICE_V2, service);
}

export const desktopArtifactContentAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_ARTIFACT_CONTENT_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopArtifactContentAuthorityV2,
});

export function createDesktopArtifactContentClientV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
  resolveConfig: () => DesktopRuntimeConfig,
): DesktopArtifactClient {
  return Object.freeze({
    async loadContent(artifactId: string, signal?: AbortSignal) {
      const prepared = prepareArtifactContentOperationV2({
        kind: 'load',
        config: resolveConfig(),
        artifactId,
        signal,
      });
      return await runDesktopArtifactContentAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.loadContent(prepared.artifactId, prepared.signal),
      );
    },
    async saveContent(
      artifactId: string,
      command: ArtifactSaveCommandV2,
      signal?: AbortSignal,
    ) {
      const prepared = prepareArtifactContentOperationV2({
        kind: 'save',
        config: resolveConfig(),
        artifactId,
        command,
        signal,
      });
      return await runDesktopArtifactContentAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.saveContent(
            prepared.artifactId,
            prepared.command,
            prepared.signal,
          ),
      );
    },
    async download(artifactId: string, signal?: AbortSignal) {
      const prepared = prepareArtifactContentOperationV2({
        kind: 'download',
        config: resolveConfig(),
        artifactId,
        signal,
      });
      return await runDesktopArtifactContentAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.download(prepared.artifactId, prepared.signal),
      );
    },
  });
}

export function withDesktopArtifactContentAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopArtifactContentOperationInputV2,
  operation: (
    authority: DesktopArtifactClient,
    prepared: PreparedArtifactContentOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopArtifactContentAuthorityOperationV2(
    actions,
    prepareArtifactContentOperationV2(input),
    operation,
  );
}

async function runDesktopArtifactContentAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedArtifactContentOperationV2,
  operation: (
    authority: DesktopArtifactClient,
    prepared: PreparedArtifactContentOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopArtifactContentAuthorityServiceV2>({
      service: DESKTOP_ARTIFACT_CONTENT_AUTHORITY_SERVICE_V2,
      version: DESKTOP_ARTIFACT_CONTENT_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.config.tenantId,
        project_id: prepared.config.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopArtifactContentAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireArtifactContentServiceV2(candidate);
      const authority = requireArtifactContentAuthorityV2(
        service.bindOperation(prepared.config),
      );
      return operation(
        createRevocableDesktopArtifactContentAuthorityV2(
          authority,
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

function createDesktopArtifactContentAuthorityV2(
  config: DesktopRuntimeConfig,
): DesktopArtifactClient {
  const operationConfig = cloneDesktopRuntimeConfigV2(config);
  return createHttpDesktopArtifactClient(operationConfig);
}

function createRevocableDesktopArtifactContentAuthorityV2(
  authority: DesktopArtifactClient,
  isOperationActive: () => boolean,
): DesktopArtifactClient {
  const requireActive = () => {
    if (!isOperationActive()) {
      throw new RuntimeV2Error(
        'desktop_artifact_content_operation_released',
        'desktop artifact content operation has been released',
      );
    }
  };
  return Object.freeze({
    loadContent(artifactId: string, signal?: AbortSignal) {
      requireActive();
      const preparedArtifactId = cloneArtifactIdV2(artifactId);
      const preparedSignal = cloneOptionalSignalV2(signal);
      return authority
        .loadContent(preparedArtifactId, preparedSignal)
        .then((value) => assertArtifactContentResponseV2(value, preparedArtifactId));
    },
    saveContent(
      artifactId: string,
      command: ArtifactSaveCommandV2,
      signal?: AbortSignal,
    ) {
      requireActive();
      const preparedArtifactId = cloneArtifactIdV2(artifactId);
      const preparedCommand = cloneSaveCommandV2(command);
      const preparedSignal = cloneOptionalSignalV2(signal);
      return authority
        .saveContent(preparedArtifactId, preparedCommand, preparedSignal)
        .then((value) =>
          assertArtifactSaveReceiptV2(value, preparedArtifactId, preparedCommand),
        );
    },
    download(artifactId: string, signal?: AbortSignal) {
      requireActive();
      const preparedArtifactId = cloneArtifactIdV2(artifactId);
      const preparedSignal = cloneOptionalSignalV2(signal);
      return authority.download(preparedArtifactId, preparedSignal).then((value) => {
        if (!(value instanceof Blob)) {
          throw new DesktopArtifactRequestError({
            reasonCode: 'artifact_download_contract_invalid',
          });
        }
        return value;
      });
    },
  });
}

function prepareArtifactContentOperationV2(
  input: Extract<DesktopArtifactContentOperationInputV2, { kind: 'save' }>,
): PreparedArtifactContentSaveOperationV2;
function prepareArtifactContentOperationV2(
  input: DesktopArtifactContentOperationInputV2,
): PreparedArtifactContentOperationV2;
function prepareArtifactContentOperationV2(
  input: DesktopArtifactContentOperationInputV2,
): PreparedArtifactContentOperationV2 {
  if (!isPlainRecordV2(input)) throw invalidArtifactContentInputV2();
  const config = cloneDesktopRuntimeConfigV2(input.config);
  const artifactId = cloneArtifactIdV2(input.artifactId);
  const signal = cloneOptionalSignalV2(input.signal);
  if (input.kind === 'save') {
    return Object.freeze({
      kind: 'save',
      config,
      artifactId,
      command: cloneSaveCommandV2(input.command),
      ...(signal === undefined ? {} : { signal }),
    });
  }
  if (input.kind !== 'download' && input.kind !== 'load') {
    throw invalidArtifactContentInputV2();
  }
  return Object.freeze({
    kind: input.kind,
    config,
    artifactId,
    ...(signal === undefined ? {} : { signal }),
  });
}

function cloneDesktopRuntimeConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidArtifactContentInputV2();
  const copy: DesktopRuntimeConfig = {
    apiBaseUrl: config.apiBaseUrl,
    deviceAuthorizationBaseUrl: config.deviceAuthorizationBaseUrl,
    apiKey: config.apiKey,
    localApiToken: config.localApiToken,
    tenantId: config.tenantId,
    projectId: config.projectId,
    workspaceId: config.workspaceId,
    mode: config.mode,
    workspaceRoot: config.workspaceRoot,
  };
  if (
    Object.values(copy).some((value) => typeof value !== 'string') ||
    (copy.mode !== 'cloud' && copy.mode !== 'local') ||
    !isCanonicalStringV2(copy.apiBaseUrl) ||
    !isCanonicalStringV2(copy.tenantId) ||
    !isCanonicalStringV2(copy.projectId)
  ) {
    throw invalidArtifactContentInputV2();
  }
  return Object.freeze(copy);
}

function cloneArtifactIdV2(value: unknown): string {
  if (typeof value !== 'string') throw invalidArtifactIdV2();
  const artifactId = value.trim();
  if (!artifactId || artifactId.length > 256) throw invalidArtifactIdV2();
  return artifactId;
}

function cloneSaveCommandV2(value: unknown): ArtifactSaveCommandV2 {
  if (
    !isPlainRecordV2(value) ||
    value.contract_version !== 2 ||
    !Number.isSafeInteger(value.expected_revision) ||
    Number(value.expected_revision) < 0 ||
    typeof value.content_hash !== 'string' ||
    !SHA256_CONTENT_HASH_PATTERN_V2.test(value.content_hash) ||
    typeof value.idempotency_key !== 'string' ||
    !IDEMPOTENCY_KEY_PATTERN_V2.test(value.idempotency_key) ||
    typeof value.content !== 'string'
  ) {
    throw invalidArtifactContentInputV2();
  }
  return Object.freeze({
    contract_version: 2,
    expected_revision: Number(value.expected_revision),
    content_hash: value.content_hash,
    idempotency_key: value.idempotency_key,
    content: value.content,
  });
}

function cloneOptionalSignalV2(value: unknown): AbortSignal | undefined {
  if (value === undefined) return undefined;
  if (typeof AbortSignal === 'undefined' || !(value instanceof AbortSignal)) {
    throw invalidArtifactContentInputV2();
  }
  return value;
}

function assertArtifactContentResponseV2(
  value: unknown,
  artifactId: string,
): ArtifactContentContractV2 {
  const result = readArtifactContentContractV2(value);
  if (!result.ok || result.value.artifact_id !== artifactId) {
    throw new DesktopArtifactRequestError({
      reasonCode: 'artifact_content_contract_invalid',
    });
  }
  return Object.freeze({ ...result.value });
}

function assertArtifactSaveReceiptV2(
  value: unknown,
  artifactId: string,
  command: ArtifactSaveCommandV2,
): ArtifactSaveReceipt {
  if (
    !isPlainRecordV2(value) ||
    value.artifact_id !== artifactId ||
    !Number.isSafeInteger(value.revision) ||
    Number(value.revision) < command.expected_revision ||
    value.content_hash !== command.content_hash ||
    typeof value.duplicate !== 'boolean'
  ) {
    throw new DesktopArtifactRequestError({
      reasonCode: 'artifact_save_receipt_invalid',
    });
  }
  return Object.freeze({
    artifact_id: artifactId,
    revision: Number(value.revision),
    content_hash: command.content_hash,
    duplicate: value.duplicate,
  });
}

function requireArtifactContentServiceV2(
  value: unknown,
): DesktopArtifactContentAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).some((key) => key !== 'bindOperation') ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidArtifactContentServiceV2();
  }
  return value as unknown as DesktopArtifactContentAuthorityServiceV2;
}

function requireArtifactContentAuthorityV2(value: unknown): DesktopArtifactClient {
  const methods = new Set(['download', 'loadContent', 'saveContent']);
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).some((key) => !methods.has(key)) ||
    typeof value.loadContent !== 'function' ||
    typeof value.saveContent !== 'function' ||
    typeof value.download !== 'function'
  ) {
    throw invalidArtifactContentServiceV2();
  }
  return value as unknown as DesktopArtifactClient;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopArtifactContentAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function invalidArtifactContentInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_artifact_content_input_invalid',
    'desktop artifact content operation input is invalid',
  );
}

function invalidArtifactContentServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_artifact_content_service_invalid',
    'desktop artifact content authority service is invalid',
  );
}

function invalidArtifactIdV2(): DesktopArtifactRequestError {
  return new DesktopArtifactRequestError({ reasonCode: 'artifact_id_invalid' });
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function isCanonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === DESKTOP_ARTIFACT_CONTENT_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_artifact_content_authority_catalog_missing',
      'desktop artifact content authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
