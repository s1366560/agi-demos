import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import { DesktopApiClient } from '../api/client';
import type {
  DesktopSearchRequest,
  DesktopSearchResponse,
} from '../api/searchContract';
import type { DesktopRuntimeConfig } from '../types';
import {
  assertProjectSearchResponseV2,
  cloneProjectSearchRequestV2,
  cloneProjectSearchRuntimeConfigV2,
  cloneProjectSearchScopeV2,
  projectSearchInputInvalidV2,
  type DesktopProjectSearchScopeV2,
} from './desktopProjectSearchContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_PROJECT_SEARCH_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-search-authority';
export const DESKTOP_PROJECT_SEARCH_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-search-authority';
export const DESKTOP_PROJECT_SEARCH_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopProjectSearchClientV2 {
  readonly searchProject: (
    request: DesktopSearchRequest,
    scope?: DesktopProjectSearchScopeV2,
  ) => Promise<DesktopSearchResponse>;
}

export interface DesktopProjectSearchAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
  ) => DesktopProjectSearchClientV2;
}

export type DesktopProjectSearchOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  request: DesktopSearchRequest;
  scope?: DesktopProjectSearchScopeV2;
}>;

type PreparedProjectSearchOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  request: DesktopSearchRequest;
  scope: DesktopProjectSearchScopeV2;
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

export class DesktopProjectSearchAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopProjectSearchAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopProjectSearchAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_project_search_authority_config_invalid',
      'desktop Project Search authority requires desktop-api-client strategy',
    );
  }
  const service: DesktopProjectSearchAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopProjectSearchAuthorityV2,
  });
  context.provide(DESKTOP_PROJECT_SEARCH_AUTHORITY_SERVICE_V2, service);
}

export const desktopProjectSearchAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_PROJECT_SEARCH_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedContractDigestV2(),
    apply: applyDesktopProjectSearchAuthorityV2,
  });

export function createDesktopProjectSearchOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
  resolveConfig: () => DesktopRuntimeConfig,
): DesktopProjectSearchClientV2 {
  return Object.freeze({
    async searchProject(
      request: DesktopSearchRequest,
      scope?: DesktopProjectSearchScopeV2,
    ) {
      const prepared = prepareProjectSearchOperationV2({
        config: resolveConfig(),
        request,
        scope,
      });
      return await runProjectSearchAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.searchProject(prepared.request, prepared.scope),
      );
    },
  });
}

export function withDesktopProjectSearchAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopProjectSearchOperationInputV2,
  operation: (
    authority: DesktopProjectSearchClientV2,
    prepared: PreparedProjectSearchOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runProjectSearchAuthorityOperationV2(
    actions,
    prepareProjectSearchOperationV2(input),
    operation,
  );
}

async function runProjectSearchAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedProjectSearchOperationV2,
  operation: (
    authority: DesktopProjectSearchClientV2,
    prepared: PreparedProjectSearchOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  prepared.scope.signal?.throwIfAborted();
  const admission =
    await actions.acquireServiceOperationLease<DesktopProjectSearchAuthorityServiceV2>({
      service: DESKTOP_PROJECT_SEARCH_AUTHORITY_SERVICE_V2,
      version: DESKTOP_PROJECT_SEARCH_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.config.tenantId,
        project_id: prepared.config.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopProjectSearchAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireProjectSearchServiceV2(candidate);
      const authority = requireProjectSearchAuthorityV2(
        service.bindOperation(prepared.config),
      );
      return operation(
        createRevocableProjectSearchAuthorityV2(
          authority,
          prepared.config,
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

function createDesktopProjectSearchAuthorityV2(
  config: DesktopRuntimeConfig,
): DesktopProjectSearchClientV2 {
  const operationConfig = cloneProjectSearchRuntimeConfigV2(config);
  const client = new DesktopApiClient(operationConfig);
  return Object.freeze({
    searchProject: (
      request: DesktopSearchRequest,
      scope?: DesktopProjectSearchScopeV2,
    ) => client.searchProject(request, scope),
  });
}

function createRevocableProjectSearchAuthorityV2(
  authority: DesktopProjectSearchClientV2,
  config: DesktopRuntimeConfig,
  isOperationActive: () => boolean,
): DesktopProjectSearchClientV2 {
  return Object.freeze({
    async searchProject(
      request: DesktopSearchRequest,
      scope?: DesktopProjectSearchScopeV2,
    ) {
      if (!isOperationActive()) {
        throw new RuntimeV2Error(
          'desktop_project_search_operation_released',
          'desktop Project Search operation has been released',
        );
      }
      const prepared = prepareProjectSearchOperationV2({
        config,
        request,
        scope,
      });
      const response = await authority.searchProject(
        prepared.request,
        prepared.scope,
      );
      return assertProjectSearchResponseV2(response, prepared.request);
    },
  });
}

function prepareProjectSearchOperationV2(
  input: DesktopProjectSearchOperationInputV2,
): PreparedProjectSearchOperationV2 {
  if (!isPlainRecordV2(input)) throw projectSearchInputInvalidV2();
  const config = cloneProjectSearchRuntimeConfigV2(input.config);
  const scope = cloneProjectSearchScopeV2(input.scope, config);
  const request = cloneProjectSearchRequestV2(input.request, scope);
  return Object.freeze({ config, request, scope });
}

function requireProjectSearchServiceV2(
  value: unknown,
): DesktopProjectSearchAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).some((key) => key !== 'bindOperation') ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidProjectSearchServiceV2();
  }
  return value as unknown as DesktopProjectSearchAuthorityServiceV2;
}

function requireProjectSearchAuthorityV2(
  value: unknown,
): DesktopProjectSearchClientV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).some((key) => key !== 'searchProject') ||
    typeof value.searchProject !== 'function'
  ) {
    throw invalidProjectSearchServiceV2();
  }
  return value as unknown as DesktopProjectSearchClientV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (
    actions !== null &&
    typeof actions.acquireServiceOperationLease === 'function'
  ) {
    return actions;
  }
  throw new DesktopProjectSearchAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function invalidProjectSearchServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_search_service_invalid',
    'desktop Project Search authority service is invalid',
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
    (candidate) =>
      candidate.module_ref === DESKTOP_PROJECT_SEARCH_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_project_search_authority_catalog_missing',
      'desktop Project Search authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
