import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  EvolutionRouteClient,
  EvolutionRouteConfig,
  EvolutionRouteObservation,
} from '../features/settings-routes/evolutionRouteClient';
import type { DesktopRuntimeConfig } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import { createDesktopTenantEvolutionHttpProjectionV2 } from './desktopTenantEvolutionHttpProjectionV2';
import {
  freezeTenantEvolutionConfigV2,
  prepareTenantEvolutionInputV2,
  prepareTenantEvolutionReviewV2,
  prepareTenantEvolutionUpdateV2,
  requireTenantEvolutionConfigV2,
  requireTenantEvolutionObservationV2,
  type DesktopTenantEvolutionInputV2,
  type DesktopTenantEvolutionReviewInputV2,
  type DesktopTenantEvolutionUpdateInputV2,
} from './desktopTenantEvolutionOperationContractV2';

export const DESKTOP_TENANT_EVOLUTION_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-evolution-authority';
export const DESKTOP_TENANT_EVOLUTION_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-evolution-authority';
export const DESKTOP_TENANT_EVOLUTION_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopTenantEvolutionAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig): EvolutionRouteClient;
}

export interface DesktopTenantEvolutionOperationsV2 {
  observeTenantEvolution(
    input: DesktopTenantEvolutionInputV2,
  ): Promise<EvolutionRouteObservation>;
  runTenantEvolution(input: DesktopTenantEvolutionInputV2): Promise<void>;
  updateTenantEvolutionConfig(
    input: DesktopTenantEvolutionUpdateInputV2,
  ): Promise<EvolutionRouteConfig>;
  reviewTenantEvolutionJob(input: DesktopTenantEvolutionReviewInputV2): Promise<void>;
}

type Rejection =
  | Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }>
  | Readonly<{
      reasonCode: 'desktop_renderer_generation_actions_unavailable';
      runtimeCode?: undefined;
    }>;

export class DesktopTenantEvolutionAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: Rejection['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: Rejection) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantEvolutionAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTenantEvolutionAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_tenant_evolution_authority_config_invalid',
      'desktop tenant evolution authority requires desktop-api-fetch strategy',
    );
  }
  context.provide(
    DESKTOP_TENANT_EVOLUTION_AUTHORITY_SERVICE_V2,
    Object.freeze({ bindOperation: createDesktopTenantEvolutionHttpProjectionV2 }),
  );
}

export const desktopTenantEvolutionAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_TENANT_EVOLUTION_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopTenantEvolutionAuthorityV2,
});

export function createDesktopTenantEvolutionOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopTenantEvolutionOperationsV2 {
  return Object.freeze({
    observeTenantEvolution(input: DesktopTenantEvolutionInputV2) {
      const prepared = prepareTenantEvolutionInputV2(input);
      return run(resolve, prepared, async (authority) =>
        requireTenantEvolutionObservationV2(
          await authority.observe(prepared.scope, prepared.signal),
          prepared.scope,
        ),
      );
    },
    runTenantEvolution(input: DesktopTenantEvolutionInputV2) {
      const prepared = prepareTenantEvolutionInputV2(input);
      return run(resolve, prepared, async (authority) => {
        const result = await authority.run(prepared.scope, prepared.signal);
        if (result !== undefined) throw invalidService();
      });
    },
    updateTenantEvolutionConfig(input: DesktopTenantEvolutionUpdateInputV2) {
      const prepared = prepareTenantEvolutionUpdateV2(input);
      return run(resolve, prepared, async (authority) =>
        requireTenantEvolutionConfigV2(
          await authority.updateConfig(prepared.scope, prepared.update, prepared.signal),
        ),
      );
    },
    reviewTenantEvolutionJob(input: DesktopTenantEvolutionReviewInputV2) {
      const prepared = prepareTenantEvolutionReviewV2(input);
      return run(resolve, prepared, async (authority) => {
        const result = await authority.reviewJob(
          prepared.scope,
          prepared.jobId,
          prepared.action,
          prepared.signal,
        );
        if (result !== undefined) throw invalidService();
      });
    },
  });
}

export function createDesktopTenantEvolutionClientV2(
  operations: DesktopTenantEvolutionOperationsV2,
  config: DesktopRuntimeConfig,
): EvolutionRouteClient {
  const frozen = freezeTenantEvolutionConfigV2(config);
  return Object.freeze({
    observe: (scope, signal) =>
      operations.observeTenantEvolution({
        config: frozen,
        scope,
        ...(signal === undefined ? {} : { signal }),
      }),
    run: (scope, signal) =>
      operations.runTenantEvolution({
        config: frozen,
        scope,
        ...(signal === undefined ? {} : { signal }),
      }),
    updateConfig: (scope, update, signal) =>
      operations.updateTenantEvolutionConfig({
        config: frozen,
        scope,
        update,
        ...(signal === undefined ? {} : { signal }),
      }),
    reviewJob: (scope, jobId, action, signal) =>
      operations.reviewTenantEvolutionJob({
        config: frozen,
        scope,
        jobId,
        action,
        ...(signal === undefined ? {} : { signal }),
      }),
  });
}

async function run<T>(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
  prepared: DesktopTenantEvolutionInputV2,
  operation: (authority: EvolutionRouteClient) => Promise<T>,
): Promise<T> {
  const actions = resolve();
  if (!actions) {
    throw new DesktopTenantEvolutionAuthorityUnavailableErrorV2({
      reasonCode: 'desktop_renderer_generation_actions_unavailable',
    });
  }
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantEvolutionAuthorityServiceV2>({
      service: DESKTOP_TENANT_EVOLUTION_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TENANT_EVOLUTION_AUTHORITY_VERSION_V2,
      scope: Object.freeze({ kind: 'tenant', tenant_id: prepared.scope.tenantId }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopTenantEvolutionAuthorityUnavailableErrorV2(admission);
  }
  let failed = false;
  let active = true;
  try {
    return await admission.useService(async (candidate) => {
      if (
        !record(candidate) ||
        Object.keys(candidate).length !== 1 ||
        typeof candidate.bindOperation !== 'function'
      ) {
        throw invalidService();
      }
      const raw = candidate.bindOperation(prepared.config);
      if (
        !record(raw) ||
        Object.keys(raw).length !== 4 ||
        typeof raw.observe !== 'function' ||
        typeof raw.run !== 'function' ||
        typeof raw.updateConfig !== 'function' ||
        typeof raw.reviewJob !== 'function'
      ) {
        throw invalidService();
      }
      const authority = Object.freeze({
        observe: (...args: Parameters<EvolutionRouteClient['observe']>) => {
          assertActive(active);
          return raw.observe(...args);
        },
        run: (...args: Parameters<EvolutionRouteClient['run']>) => {
          assertActive(active);
          return raw.run(...args);
        },
        updateConfig: (...args: Parameters<EvolutionRouteClient['updateConfig']>) => {
          assertActive(active);
          return raw.updateConfig(...args);
        },
        reviewJob: (...args: Parameters<EvolutionRouteClient['reviewJob']>) => {
          assertActive(active);
          return raw.reviewJob(...args);
        },
      });
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

function assertActive(active: boolean): void {
  if (!active) {
    throw new RuntimeV2Error(
      'desktop_tenant_evolution_operation_released',
      'desktop tenant evolution operation released',
    );
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalidService(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_evolution_service_invalid',
    'desktop tenant evolution authority service invalid',
  );
}

function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_TENANT_EVOLUTION_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry) {
    throw new RuntimeV2Error(
      'desktop_tenant_evolution_authority_catalog_missing',
      'desktop tenant evolution authority absent from catalog',
    );
  }
  return entry.contract_digest;
}
