import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import {
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../api/client';
import { desktopApiFetch } from '../api/cloudRequestBroker';
import type {
  TenantProjectRecord,
  TenantProjectsClient,
  TenantProjectsListQuery,
  TenantProjectsListSnapshot,
  TenantProjectsMutationInput,
  TenantProjectsScope,
} from '../features/tenant/tenantProjectsClient';
import type { DesktopRuntimeConfig } from '../types';
import {
  requireDesktopTenantProjectRecordV2,
  requireDesktopTenantProjectsSnapshotV2,
} from './desktopTenantProjectsContractV2';
import {
  desktopTenantProjectDeletePathV2,
  desktopTenantProjectMutationBodyV2,
  desktopTenantProjectPathV2,
  desktopTenantProjectsCollectionPathV2,
  desktopTenantProjectsListPathV2,
  projectDesktopTenantProjectRecordV2,
  projectDesktopTenantProjectsCloudSnapshotV2,
  projectDesktopTenantProjectsLocalSnapshotV2,
  tenantProjectsContractErrorV2,
} from './desktopTenantProjectsHttpProjectionV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import {
  cloneDesktopTenantProjectsRuntimeConfigV2,
  cloneDesktopTenantProjectsScopeV2,
  prepareTenantProjectCreateOperationV2,
  prepareTenantProjectDeleteOperationV2,
  prepareTenantProjectGetOperationV2,
  prepareTenantProjectUpdateOperationV2,
  prepareTenantProjectsBaseOperationV2,
  prepareTenantProjectsListOperationV2,
  type DesktopTenantProjectCreateInputV2,
  type DesktopTenantProjectDeleteInputV2,
  type DesktopTenantProjectGetInputV2,
  type DesktopTenantProjectUpdateInputV2,
  type DesktopTenantProjectsListInputV2,
  type DesktopTenantProjectsOperationInputV2,
  type PreparedTenantProjectsOperationV2,
} from './desktopTenantProjectsOperationContractV2';

export type {
  DesktopTenantProjectCreateInputV2,
  DesktopTenantProjectDeleteInputV2,
  DesktopTenantProjectGetInputV2,
  DesktopTenantProjectUpdateInputV2,
  DesktopTenantProjectsListInputV2,
  DesktopTenantProjectsOperationInputV2,
} from './desktopTenantProjectsOperationContractV2';

export const DESKTOP_TENANT_PROJECTS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-projects-authority';
export const DESKTOP_TENANT_PROJECTS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-projects-authority';
export const DESKTOP_TENANT_PROJECTS_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopTenantProjectsAuthorityV2 {
  readonly list: (
    query?: TenantProjectsListQuery,
    signal?: AbortSignal,
  ) => Promise<TenantProjectsListSnapshot>;
  readonly get: (
    projectId: string,
    signal?: AbortSignal,
  ) => Promise<TenantProjectRecord>;
  readonly create: (
    input: TenantProjectsMutationInput,
    idempotencyKey?: string,
    signal?: AbortSignal,
  ) => Promise<TenantProjectRecord>;
  readonly update: (
    projectId: string,
    input: TenantProjectsMutationInput,
    idempotencyKey?: string,
    signal?: AbortSignal,
  ) => Promise<TenantProjectRecord>;
  readonly delete: (
    projectId: string,
    idempotencyKey?: string,
    signal?: AbortSignal,
  ) => Promise<void>;
}

export interface DesktopTenantProjectsAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: TenantProjectsScope,
  ) => DesktopTenantProjectsAuthorityV2;
}

export interface DesktopTenantProjectsOperationsV2 {
  readonly listTenantProjects: (
    input: DesktopTenantProjectsListInputV2,
  ) => Promise<TenantProjectsListSnapshot>;
  readonly getTenantProject: (
    input: DesktopTenantProjectGetInputV2,
  ) => Promise<TenantProjectRecord>;
  readonly createTenantProject: (
    input: DesktopTenantProjectCreateInputV2,
  ) => Promise<TenantProjectRecord>;
  readonly updateTenantProject: (
    input: DesktopTenantProjectUpdateInputV2,
  ) => Promise<TenantProjectRecord>;
  readonly deleteTenantProject: (
    input: DesktopTenantProjectDeleteInputV2,
  ) => Promise<void>;
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

const AUTHORITY_KEYS_V2 = new Set(['list', 'get', 'create', 'update', 'delete']);

export class DesktopTenantProjectsAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantProjectsAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTenantProjectsAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_tenant_projects_authority_config_invalid',
      'desktop tenant projects authority requires desktop-api-fetch strategy',
    );
  }
  const service: DesktopTenantProjectsAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopTenantProjectsAuthorityV2,
  });
  context.provide(DESKTOP_TENANT_PROJECTS_AUTHORITY_SERVICE_V2, service);
}

export const desktopTenantProjectsAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_TENANT_PROJECTS_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedContractDigestV2(),
    apply: applyDesktopTenantProjectsAuthorityV2,
  });

export function createDesktopTenantProjectsOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopTenantProjectsOperationsV2 {
  return Object.freeze({
    listTenantProjects(input: DesktopTenantProjectsListInputV2) {
      const prepared = prepareTenantProjectsListOperationV2(input);
      return runDesktopTenantProjectsAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.list(prepared.query, prepared.signal),
      );
    },
    getTenantProject(input: DesktopTenantProjectGetInputV2) {
      const prepared = prepareTenantProjectGetOperationV2(input);
      return runDesktopTenantProjectsAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.get(prepared.projectId, prepared.signal),
      );
    },
    createTenantProject(input: DesktopTenantProjectCreateInputV2) {
      const prepared = prepareTenantProjectCreateOperationV2(input);
      return runDesktopTenantProjectsAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.create(prepared.input, prepared.idempotencyKey, prepared.signal),
      );
    },
    updateTenantProject(input: DesktopTenantProjectUpdateInputV2) {
      const prepared = prepareTenantProjectUpdateOperationV2(input);
      return runDesktopTenantProjectsAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.update(
            prepared.projectId,
            prepared.input,
            prepared.idempotencyKey,
            prepared.signal,
          ),
      );
    },
    deleteTenantProject(input: DesktopTenantProjectDeleteInputV2) {
      const prepared = prepareTenantProjectDeleteOperationV2(input);
      return runDesktopTenantProjectsAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.delete(prepared.projectId, prepared.idempotencyKey, prepared.signal),
      );
    },
  });
}

export function withDesktopTenantProjectsAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopTenantProjectsOperationInputV2,
  operation: (authority: DesktopTenantProjectsAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopTenantProjectsAuthorityOperationV2(
    actions,
    prepareTenantProjectsBaseOperationV2(input),
    operation,
  );
}

export function createDesktopTenantProjectsClientV2(
  operations: DesktopTenantProjectsOperationsV2,
  config: DesktopRuntimeConfig,
): TenantProjectsClient {
  const operationConfig = cloneDesktopTenantProjectsRuntimeConfigV2(config);
  return Object.freeze({
    async list(scope, query, options) {
      return operations.listTenantProjects({
        config: operationConfig,
        scope,
        ...(query === undefined ? {} : { query }),
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
    async get(scope, projectId, options) {
      return operations.getTenantProject({
        config: operationConfig,
        scope,
        projectId,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
    async create(scope, input, options) {
      return operations.createTenantProject({
        config: operationConfig,
        scope,
        input,
        ...(options?.idempotencyKey === undefined
          ? {}
          : { idempotencyKey: options.idempotencyKey }),
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
    async update(scope, projectId, input, options) {
      return operations.updateTenantProject({
        config: operationConfig,
        scope,
        projectId,
        input,
        ...(options?.idempotencyKey === undefined
          ? {}
          : { idempotencyKey: options.idempotencyKey }),
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
    async delete(scope, projectId, options) {
      return operations.deleteTenantProject({
        config: operationConfig,
        scope,
        projectId,
        ...(options?.idempotencyKey === undefined
          ? {}
          : { idempotencyKey: options.idempotencyKey }),
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      });
    },
  });
}

async function runDesktopTenantProjectsAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedTenantProjectsOperationV2,
  operation: (authority: DesktopTenantProjectsAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantProjectsAuthorityServiceV2>({
      service: DESKTOP_TENANT_PROJECTS_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TENANT_PROJECTS_AUTHORITY_VERSION_V2,
      scope: Object.freeze({ kind: 'tenant', tenant_id: prepared.scope.tenantId }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopTenantProjectsAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireTenantProjectsServiceV2(candidate);
      const authority = requireTenantProjectsAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope),
      );
      return operation(
        createRevocableTenantProjectsAuthorityV2(
          authority,
          prepared.scope,
          () => operationActive,
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

function createDesktopTenantProjectsAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: TenantProjectsScope,
): DesktopTenantProjectsAuthorityV2 {
  const operationConfig = cloneDesktopTenantProjectsRuntimeConfigV2(config);
  const operationScope = cloneDesktopTenantProjectsScopeV2(scope, operationConfig);
  return Object.freeze({
    async list(query?: TenantProjectsListQuery, signal?: AbortSignal) {
      const projects = await requestJsonV2(
        operationConfig,
        desktopTenantProjectsListPathV2(operationConfig, operationScope, query),
        { method: 'GET', signal },
      );
      if (operationConfig.mode === 'local') {
        return projectDesktopTenantProjectsLocalSnapshotV2(projects, operationScope);
      }
      const projectIds = cloudProjectIdsV2(projects, operationConfig);
      const [user, workspaceContext, ...memberSnapshots] = await Promise.all([
        requestJsonV2(operationConfig, '/api/v1/auth/me', { method: 'GET', signal }),
        requestJsonV2(operationConfig, '/api/v1/workspace-context', {
          method: 'GET',
          signal,
        }),
        ...projectIds.map((projectId) =>
          requestJsonV2(
            operationConfig,
            `/api/v1/projects/${encodeURIComponent(projectId)}/members`,
            { method: 'GET', signal },
          ),
        ),
      ]);
      return projectDesktopTenantProjectsCloudSnapshotV2(
        projects,
        user,
        workspaceContext,
        memberSnapshots,
        operationScope,
      );
    },
    async get(projectId: string, signal?: AbortSignal) {
      const params = new URLSearchParams({ tenant_id: operationScope.tenantId });
      const payload = await requestJsonV2(
        operationConfig,
        `${desktopTenantProjectPathV2(operationConfig, projectId)}?${params}`,
        { method: 'GET', signal },
      );
      return projectDesktopTenantProjectRecordV2(payload, operationScope);
    },
    async create(
      input: TenantProjectsMutationInput,
      idempotencyKey?: string,
      signal?: AbortSignal,
    ) {
      const payload = await requestJsonV2(
        operationConfig,
        desktopTenantProjectsCollectionPathV2(operationConfig),
        {
          method: 'POST',
          body: desktopTenantProjectMutationBodyV2(operationScope, input, true),
          idempotencyKey,
          signal,
        },
      );
      return projectDesktopTenantProjectRecordV2(payload, operationScope);
    },
    async update(
      projectId: string,
      input: TenantProjectsMutationInput,
      idempotencyKey?: string,
      signal?: AbortSignal,
    ) {
      const payload = await requestJsonV2(
        operationConfig,
        desktopTenantProjectPathV2(operationConfig, projectId),
        {
          method: 'PUT',
          body: desktopTenantProjectMutationBodyV2(operationScope, input, false),
          idempotencyKey,
          signal,
        },
      );
      return projectDesktopTenantProjectRecordV2(payload, operationScope);
    },
    async delete(
      projectId: string,
      idempotencyKey?: string,
      signal?: AbortSignal,
    ) {
      await requestJsonV2(
        operationConfig,
        desktopTenantProjectDeletePathV2(operationConfig, projectId),
        {
          method: operationConfig.mode === 'local' ? 'POST' : 'DELETE',
          idempotencyKey,
          signal,
          allowEmpty: true,
        },
      );
    },
  });
}

function createRevocableTenantProjectsAuthorityV2(
  authority: DesktopTenantProjectsAuthorityV2,
  scope: TenantProjectsScope,
  isOperationActive: () => boolean,
): DesktopTenantProjectsAuthorityV2 {
  return Object.freeze({
    async list(query?: TenantProjectsListQuery, signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.list(query, signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopTenantProjectsSnapshotV2(result, scope);
    },
    async get(projectId: string, signal?: AbortSignal) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.get(projectId, signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopTenantProjectRecordV2(result, scope);
    },
    async create(
      input: TenantProjectsMutationInput,
      idempotencyKey?: string,
      signal?: AbortSignal,
    ) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.create(input, idempotencyKey, signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopTenantProjectRecordV2(result, scope);
    },
    async update(
      projectId: string,
      input: TenantProjectsMutationInput,
      idempotencyKey?: string,
      signal?: AbortSignal,
    ) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.update(projectId, input, idempotencyKey, signal);
      requireOperationActiveV2(isOperationActive);
      return requireDesktopTenantProjectRecordV2(result, scope);
    },
    async delete(
      projectId: string,
      idempotencyKey?: string,
      signal?: AbortSignal,
    ) {
      requireOperationActiveV2(isOperationActive);
      const result = await authority.delete(projectId, idempotencyKey, signal);
      requireOperationActiveV2(isOperationActive);
      if (result !== undefined) throw invalidServiceV2();
    },
  });
}

type RequestOptionsV2 = Readonly<{
  method: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: Readonly<Record<string, unknown>>;
  idempotencyKey?: string;
  signal?: AbortSignal;
  allowEmpty?: boolean;
}>;

async function requestJsonV2(
  config: DesktopRuntimeConfig,
  path: string,
  options: RequestOptionsV2,
): Promise<unknown> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  if (options.body !== undefined) headers.set('Content-Type', 'application/json');
  if (options.idempotencyKey !== undefined) {
    headers.set('Idempotency-Key', options.idempotencyKey);
  }
  const response = await desktopApiFetch(config, path, {
    method: options.method,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });
  if (options.allowEmpty && response.status === 204) return null;
  const contentType = response.headers.get('content-type') ?? '';
  const isJson = contentType.toLowerCase().includes('application/json');
  const payload = isJson
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '');
  if (!response.ok) {
    throw new DesktopApiError(errorMessageV2(response.status, payload), response.status, payload);
  }
  if (!isJson || payload === null) {
    throw tenantProjectsContractErrorV2(contractReasonV2(config));
  }
  return payload;
}

function cloudProjectIdsV2(
  payload: unknown,
  config: DesktopRuntimeConfig,
): readonly string[] {
  if (!isPlainRecordV2(payload) || !Array.isArray(payload.projects)) {
    throw tenantProjectsContractErrorV2(contractReasonV2(config));
  }
  const projectIds = payload.projects.map((project) => {
    if (!isPlainRecordV2(project) || !isCanonicalStringV2(project.id)) {
      throw tenantProjectsContractErrorV2(contractReasonV2(config));
    }
    return project.id;
  });
  if (new Set(projectIds).size !== projectIds.length) {
    throw tenantProjectsContractErrorV2(contractReasonV2(config));
  }
  return Object.freeze(projectIds);
}

function requireTenantProjectsServiceV2(
  value: unknown,
): DesktopTenantProjectsAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopTenantProjectsAuthorityServiceV2;
}

function requireTenantProjectsAuthorityV2(value: unknown): DesktopTenantProjectsAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, AUTHORITY_KEYS_V2) ||
    typeof value.list !== 'function' ||
    typeof value.get !== 'function' ||
    typeof value.create !== 'function' ||
    typeof value.update !== 'function' ||
    typeof value.delete !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopTenantProjectsAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopTenantProjectsAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireOperationActiveV2(isOperationActive: () => boolean): void {
  if (isOperationActive()) return;
  throw new RuntimeV2Error(
    'desktop_tenant_projects_operation_released',
    'desktop tenant projects operation has been released',
  );
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_projects_service_invalid',
    'desktop tenant projects authority service is invalid',
  );
}

function contractReasonV2(config: DesktopRuntimeConfig): string {
  return `${config.mode}_tenant_projects_contract_invalid`;
}

function errorMessageV2(status: number, payload: unknown): string {
  if (isPlainRecordV2(payload) && typeof payload.detail === 'string' && payload.detail.trim()) {
    return payload.detail;
  }
  const reasonCode = structuredReasonCodeV2(payload);
  return reasonCode ?? `tenant_projects_http_${status}`;
}

function structuredReasonCodeV2(payload: unknown): string | null {
  if (!isPlainRecordV2(payload)) return null;
  if (typeof payload.reason_code === 'string') return payload.reason_code;
  return isPlainRecordV2(payload.detail) && typeof payload.detail.reason_code === 'string'
    ? payload.detail.reason_code
    : null;
}

function hasExactKeysV2(
  value: Record<string, unknown>,
  expected: ReadonlySet<string>,
): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
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
    (candidate) => candidate.module_ref === DESKTOP_TENANT_PROJECTS_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_tenant_projects_authority_catalog_missing',
      'desktop tenant projects authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
