import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  TenantGene,
  TenantGeneReview,
  TenantGenesClient,
  TenantGenesSnapshot,
} from '../features/tenant-admin/tenantGenesClient';
import type {
  TenantManagementRequestOptions,
  TenantManagementScope,
} from '../features/tenant-admin/tenantManagementHttp';
import type { DesktopRuntimeConfig } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import { createDesktopTenantGenesHttpProjectionV2 } from './desktopTenantGenesHttpProjectionV2';
import {
  freezeDesktopTenantGenesConfigV2,
  prepareDesktopTenantGenesCreateReviewV2,
  prepareDesktopTenantGenesCreateV2,
  prepareDesktopTenantGenesDeleteReviewV2,
  prepareDesktopTenantGenesGeneIdV2,
  prepareDesktopTenantGenesInstallV2,
  prepareDesktopTenantGenesLoadV2,
  prepareDesktopTenantGenesRateV2,
  prepareDesktopTenantGenesUpdateV2,
  requireDesktopTenantGeneReviewV2,
  requireDesktopTenantGeneReviewsV2,
  requireDesktopTenantGenesJsonRecordV2,
  requireDesktopTenantGenesJsonRecordsV2,
  requireDesktopTenantGenesSnapshotV2,
  requireDesktopTenantGenesVoidV2,
  requireDesktopTenantGeneV2,
  type DesktopTenantGenesCreateInputV2,
  type DesktopTenantGenesCreateReviewInputV2,
  type DesktopTenantGenesDeleteReviewInputV2,
  type DesktopTenantGenesGeneIdInputV2,
  type DesktopTenantGenesInstallInputV2,
  type DesktopTenantGenesLoadInputV2,
  type DesktopTenantGenesRateInputV2,
  type DesktopTenantGenesUpdateInputV2,
} from './desktopTenantGenesOperationContractV2';

export const DESKTOP_TENANT_GENES_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-genes-authority';
export const DESKTOP_TENANT_GENES_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-genes-authority';
export const DESKTOP_TENANT_GENES_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopTenantGenesAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig, scope: TenantManagementScope): TenantGenesClient;
}

export interface DesktopTenantGenesOperationsV2 {
  loadTenantGenes(input: DesktopTenantGenesLoadInputV2): Promise<TenantGenesSnapshot>;
  createTenantGene(input: DesktopTenantGenesCreateInputV2): Promise<TenantGene>;
  updateTenantGene(input: DesktopTenantGenesUpdateInputV2): Promise<TenantGene>;
  deleteTenantGene(input: DesktopTenantGenesGeneIdInputV2): Promise<void>;
  publishTenantGene(input: DesktopTenantGenesGeneIdInputV2): Promise<TenantGene>;
  unpublishTenantGene(input: DesktopTenantGenesGeneIdInputV2): Promise<TenantGene>;
  installTenantGene(
    input: DesktopTenantGenesInstallInputV2,
  ): Promise<Readonly<Record<string, unknown>>>;
  rateTenantGene(
    input: DesktopTenantGenesRateInputV2,
  ): Promise<Readonly<Record<string, unknown>>>;
  listTenantGeneGenomes(
    input: DesktopTenantGenesLoadInputV2,
  ): Promise<readonly Readonly<Record<string, unknown>>[]>;
  loadTenantGeneEvolution(
    input: DesktopTenantGenesLoadInputV2,
  ): Promise<Readonly<Record<string, unknown>>>;
  listTenantGeneReviews(
    input: DesktopTenantGenesGeneIdInputV2,
  ): Promise<readonly TenantGeneReview[]>;
  createTenantGeneReview(input: DesktopTenantGenesCreateReviewInputV2): Promise<TenantGeneReview>;
  deleteTenantGeneReview(input: DesktopTenantGenesDeleteReviewInputV2): Promise<void>;
}

type Rejection =
  | Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }>
  | Readonly<{
      reasonCode: 'desktop_renderer_generation_actions_unavailable';
      runtimeCode?: undefined;
    }>;

export class DesktopTenantGenesAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: Rejection['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: Rejection) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantGenesAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTenantGenesAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_tenant_genes_authority_config_invalid',
      'desktop tenant genes authority requires desktop-api-fetch strategy',
    );
  }
  context.provide(
    DESKTOP_TENANT_GENES_AUTHORITY_SERVICE_V2,
    Object.freeze({
      bindOperation(configValue: DesktopRuntimeConfig, _scope: TenantManagementScope) {
        return createDesktopTenantGenesHttpProjectionV2(configValue);
      },
    }),
  );
}

export const desktopTenantGenesAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_TENANT_GENES_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopTenantGenesAuthorityV2,
});

export function createDesktopTenantGenesOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopTenantGenesOperationsV2 {
  return Object.freeze({
    loadTenantGenes(input: DesktopTenantGenesLoadInputV2) {
      const prepared = prepareDesktopTenantGenesLoadV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantGenesSnapshotV2(
          await authority.load(prepared.scope, requestOptions(prepared.signal)),
          prepared.scope,
        ),
      );
    },
    createTenantGene(input: DesktopTenantGenesCreateInputV2) {
      const prepared = prepareDesktopTenantGenesCreateV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantGeneV2(
          await authority.createGene(
            prepared.scope,
            prepared.input,
            requestOptions(prepared.signal),
          ),
          prepared.scope,
        ),
      );
    },
    updateTenantGene(input: DesktopTenantGenesUpdateInputV2) {
      const prepared = prepareDesktopTenantGenesUpdateV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantGeneV2(
          await authority.updateGene(
            prepared.scope,
            prepared.geneId,
            prepared.input,
            requestOptions(prepared.signal),
          ),
          prepared.scope,
        ),
      );
    },
    deleteTenantGene(input: DesktopTenantGenesGeneIdInputV2) {
      const prepared = prepareDesktopTenantGenesGeneIdV2(input);
      return run(resolve, prepared, async (authority) => {
        requireDesktopTenantGenesVoidV2(
          await authority.deleteGene(
            prepared.scope,
            prepared.geneId,
            requestOptions(prepared.signal),
          ),
        );
      });
    },
    publishTenantGene(input: DesktopTenantGenesGeneIdInputV2) {
      const prepared = prepareDesktopTenantGenesGeneIdV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantGeneV2(
          await authority.publishGene(
            prepared.scope,
            prepared.geneId,
            requestOptions(prepared.signal),
          ),
          prepared.scope,
        ),
      );
    },
    unpublishTenantGene(input: DesktopTenantGenesGeneIdInputV2) {
      const prepared = prepareDesktopTenantGenesGeneIdV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantGeneV2(
          await authority.unpublishGene(
            prepared.scope,
            prepared.geneId,
            requestOptions(prepared.signal),
          ),
          prepared.scope,
        ),
      );
    },
    installTenantGene(input: DesktopTenantGenesInstallInputV2) {
      const prepared = prepareDesktopTenantGenesInstallV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantGenesJsonRecordV2(
          await authority.installGene(
            prepared.scope,
            prepared.instanceId,
            prepared.geneId,
            requestOptions(prepared.signal),
          ),
        ),
      );
    },
    rateTenantGene(input: DesktopTenantGenesRateInputV2) {
      const prepared = prepareDesktopTenantGenesRateV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantGenesJsonRecordV2(
          await authority.rateGene(
            prepared.scope,
            prepared.geneId,
            prepared.rating,
            prepared.comment,
            requestOptions(prepared.signal),
          ),
        ),
      );
    },
    listTenantGeneGenomes(input: DesktopTenantGenesLoadInputV2) {
      const prepared = prepareDesktopTenantGenesLoadV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantGenesJsonRecordsV2(
          await authority.listGenomes(prepared.scope, requestOptions(prepared.signal)),
        ),
      );
    },
    loadTenantGeneEvolution(input: DesktopTenantGenesLoadInputV2) {
      const prepared = prepareDesktopTenantGenesLoadV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantGenesJsonRecordV2(
          await authority.listEvolution(prepared.scope, requestOptions(prepared.signal)),
        ),
      );
    },
    listTenantGeneReviews(input: DesktopTenantGenesGeneIdInputV2) {
      const prepared = prepareDesktopTenantGenesGeneIdV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantGeneReviewsV2(
          await authority.listReviews(
            prepared.scope,
            prepared.geneId,
            requestOptions(prepared.signal),
          ),
          prepared.geneId,
        ),
      );
    },
    createTenantGeneReview(input: DesktopTenantGenesCreateReviewInputV2) {
      const prepared = prepareDesktopTenantGenesCreateReviewV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantGeneReviewV2(
          await authority.createReview(
            prepared.scope,
            prepared.geneId,
            prepared.rating,
            prepared.content,
            requestOptions(prepared.signal),
          ),
          prepared.geneId,
        ),
      );
    },
    deleteTenantGeneReview(input: DesktopTenantGenesDeleteReviewInputV2) {
      const prepared = prepareDesktopTenantGenesDeleteReviewV2(input);
      return run(resolve, prepared, async (authority) => {
        requireDesktopTenantGenesVoidV2(
          await authority.deleteReview(
            prepared.scope,
            prepared.geneId,
            prepared.reviewId,
            requestOptions(prepared.signal),
          ),
        );
      });
    },
  });
}

export function createDesktopTenantGenesClientV2(
  operations: DesktopTenantGenesOperationsV2,
  config: DesktopRuntimeConfig,
): TenantGenesClient {
  const frozen = freezeDesktopTenantGenesConfigV2(config);
  return Object.freeze({
    load: (scope, options) =>
      operations.loadTenantGenes(operationInput(frozen, scope, options)),
    createGene: (scope, input, options) =>
      operations.createTenantGene({ ...operationInput(frozen, scope, options), input }),
    updateGene: (scope, geneId, input, options) =>
      operations.updateTenantGene({
        ...operationInput(frozen, scope, options),
        geneId,
        input,
      }),
    deleteGene: (scope, geneId, options) =>
      operations.deleteTenantGene({ ...operationInput(frozen, scope, options), geneId }),
    publishGene: (scope, geneId, options) =>
      operations.publishTenantGene({ ...operationInput(frozen, scope, options), geneId }),
    unpublishGene: (scope, geneId, options) =>
      operations.unpublishTenantGene({ ...operationInput(frozen, scope, options), geneId }),
    installGene: (scope, instanceId, geneId, options) =>
      operations.installTenantGene({
        ...operationInput(frozen, scope, options),
        instanceId,
        geneId,
      }),
    rateGene: (scope, geneId, rating, comment, options) =>
      operations.rateTenantGene({
        ...operationInput(frozen, scope, options),
        geneId,
        rating,
        ...(comment === undefined ? {} : { comment }),
      }),
    listGenomes: (scope, options) =>
      operations.listTenantGeneGenomes(operationInput(frozen, scope, options)),
    listEvolution: (scope, options) =>
      operations.loadTenantGeneEvolution(operationInput(frozen, scope, options)),
    listReviews: (scope, geneId, options) =>
      operations.listTenantGeneReviews({ ...operationInput(frozen, scope, options), geneId }),
    createReview: (scope, geneId, rating, content, options) =>
      operations.createTenantGeneReview({
        ...operationInput(frozen, scope, options),
        geneId,
        rating,
        content,
      }),
    deleteReview: (scope, geneId, reviewId, options) =>
      operations.deleteTenantGeneReview({
        ...operationInput(frozen, scope, options),
        geneId,
        reviewId,
      }),
  });
}

async function run<T>(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
  prepared: DesktopTenantGenesLoadInputV2,
  operation: (authority: TenantGenesClient) => Promise<T>,
): Promise<T> {
  const actions = resolve();
  if (!actions) {
    throw new DesktopTenantGenesAuthorityUnavailableErrorV2({
      reasonCode: 'desktop_renderer_generation_actions_unavailable',
    });
  }
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantGenesAuthorityServiceV2>({
      service: DESKTOP_TENANT_GENES_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TENANT_GENES_AUTHORITY_VERSION_V2,
      scope: Object.freeze({ kind: 'tenant', tenant_id: prepared.scope.tenantId }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopTenantGenesAuthorityUnavailableErrorV2(admission);
  }
  let failed = false;
  let active = true;
  try {
    return await admission.useService(async (candidate) => {
      assertActive(active);
      const service = requireService(candidate);
      const raw = service.bindOperation(prepared.config, prepared.scope);
      const authority = wrapAuthority(raw, () => active);
      const result = await operation(authority);
      assertActive(active);
      return result;
    });
  } catch (error) {
    failed = true;
    throw error;
  } finally {
    active = false;
    try {
      await admission.release();
    } catch (error) {
      if (!failed) throw error;
    }
  }
}

function requireService(value: unknown): DesktopTenantGenesAuthorityServiceV2 {
  if (
    !record(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidService();
  }
  return value as unknown as DesktopTenantGenesAuthorityServiceV2;
}

function wrapAuthority(raw: unknown, active: () => boolean): TenantGenesClient {
  const methods = [
    'load',
    'createGene',
    'updateGene',
    'deleteGene',
    'publishGene',
    'unpublishGene',
    'installGene',
    'rateGene',
    'listGenomes',
    'listEvolution',
    'listReviews',
    'createReview',
    'deleteReview',
  ] as const;
  if (
    !record(raw) ||
    Object.keys(raw).length !== methods.length ||
    methods.some((method) => typeof raw[method] !== 'function')
  ) {
    throw invalidService();
  }
  const authority = raw as unknown as TenantGenesClient;
  return Object.freeze({
    load: (...args) => invoke(active, authority.load, args),
    createGene: (...args) => invoke(active, authority.createGene, args),
    updateGene: (...args) => invoke(active, authority.updateGene, args),
    deleteGene: (...args) => invoke(active, authority.deleteGene, args),
    publishGene: (...args) => invoke(active, authority.publishGene, args),
    unpublishGene: (...args) => invoke(active, authority.unpublishGene, args),
    installGene: (...args) => invoke(active, authority.installGene, args),
    rateGene: (...args) => invoke(active, authority.rateGene, args),
    listGenomes: (...args) => invoke(active, authority.listGenomes, args),
    listEvolution: (...args) => invoke(active, authority.listEvolution, args),
    listReviews: (...args) => invoke(active, authority.listReviews, args),
    createReview: (...args) => invoke(active, authority.createReview, args),
    deleteReview: (...args) => invoke(active, authority.deleteReview, args),
  });
}

function invoke<TArgs extends readonly unknown[], TResult>(
  active: () => boolean,
  operation: (...args: TArgs) => TResult,
  args: TArgs,
): TResult {
  assertActive(active());
  return operation(...args);
}

function operationInput(
  config: DesktopRuntimeConfig,
  scope: TenantManagementScope,
  options?: TenantManagementRequestOptions,
): DesktopTenantGenesLoadInputV2 {
  return {
    config,
    scope,
    ...(options?.signal === undefined ? {} : { signal: options.signal }),
  };
}

function requestOptions(signal?: AbortSignal): TenantManagementRequestOptions | undefined {
  return signal === undefined ? undefined : Object.freeze({ signal });
}

function assertActive(active: boolean): void {
  if (!active) {
    throw new RuntimeV2Error(
      'desktop_tenant_genes_operation_released',
      'desktop tenant genes operation released',
    );
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalidService(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_genes_service_invalid',
    'desktop tenant genes authority service invalid',
  );
}

function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_TENANT_GENES_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry) {
    throw new RuntimeV2Error(
      'desktop_tenant_genes_authority_catalog_missing',
      'desktop tenant genes authority absent from catalog',
    );
  }
  return entry.contract_digest;
}
