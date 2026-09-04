import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  TemplatesRouteClient,
  TemplatesRouteDetail,
} from '../features/settings-routes/templatesRouteClient';
import type {
  DesktopRuntimeConfig,
  ManagedSubAgent,
} from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import { createDesktopTenantTemplatesHttpProjectionV2 } from './desktopTenantTemplatesHttpProjectionV2';
import {
  freezeDesktopTenantTemplatesConfigV2,
  prepareDesktopTenantTemplatesItemV2,
  prepareDesktopTenantTemplatesLoadV2,
  prepareDesktopTenantTemplatesSeedV2,
  requireDesktopTenantTemplateDetailV2,
  requireDesktopTenantTemplateInstallV2,
  requireDesktopTenantTemplatesSnapshotV2,
  requireDesktopTenantTemplateSeedV2,
  type DesktopTenantTemplatesAuthorityV2,
  type DesktopTenantTemplatesItemInputV2,
  type DesktopTenantTemplatesLoadInputV2,
  type DesktopTenantTemplatesSeedInputV2,
  type DesktopTenantTemplatesSnapshotV2,
} from './desktopTenantTemplatesOperationContractV2';

export const DESKTOP_TENANT_TEMPLATES_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-templates-authority';
export const DESKTOP_TENANT_TEMPLATES_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-templates-authority';
export const DESKTOP_TENANT_TEMPLATES_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopTenantTemplatesAuthorityServiceV2 {
  bindOperation(
    config: DesktopRuntimeConfig,
    scope: DesktopTenantTemplatesLoadInputV2['scope'],
  ): DesktopTenantTemplatesAuthorityV2;
}

export interface DesktopTenantTemplatesOperationsV2 {
  loadTenantTemplates(
    input: DesktopTenantTemplatesLoadInputV2,
  ): Promise<DesktopTenantTemplatesSnapshotV2>;
  getTenantTemplate(
    input: DesktopTenantTemplatesItemInputV2,
  ): Promise<TemplatesRouteDetail>;
  installTenantTemplate(
    input: DesktopTenantTemplatesItemInputV2,
  ): Promise<ManagedSubAgent>;
  seedTenantTemplates(input: DesktopTenantTemplatesSeedInputV2): Promise<number>;
}

type Rejection =
  | Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }>
  | Readonly<{
      reasonCode: 'desktop_renderer_generation_actions_unavailable';
      runtimeCode?: undefined;
    }>;

export class DesktopTenantTemplatesAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: Rejection['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: Rejection) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantTemplatesAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTenantTemplatesAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_tenant_templates_authority_config_invalid',
      'desktop tenant templates authority requires desktop-api-fetch strategy',
    );
  }
  context.provide(
    DESKTOP_TENANT_TEMPLATES_AUTHORITY_SERVICE_V2,
    Object.freeze({
      bindOperation(configValue: DesktopRuntimeConfig) {
        return createDesktopTenantTemplatesHttpProjectionV2(configValue);
      },
    }),
  );
}

export const desktopTenantTemplatesAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_TENANT_TEMPLATES_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopTenantTemplatesAuthorityV2,
});

export function createDesktopTenantTemplatesOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopTenantTemplatesOperationsV2 {
  return Object.freeze({
    loadTenantTemplates(input: DesktopTenantTemplatesLoadInputV2) {
      const prepared = prepareDesktopTenantTemplatesLoadV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantTemplatesSnapshotV2(
          await authority.load(prepared.scope, prepared.query, prepared.signal),
          prepared.scope,
          prepared.query,
        ),
      );
    },
    getTenantTemplate(input: DesktopTenantTemplatesItemInputV2) {
      const prepared = prepareDesktopTenantTemplatesItemV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantTemplateDetailV2(
          await authority.get(prepared.scope, prepared.templateId, prepared.signal),
          prepared.scope.tenantId,
        ),
      );
    },
    installTenantTemplate(input: DesktopTenantTemplatesItemInputV2) {
      const prepared = prepareDesktopTenantTemplatesItemV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantTemplateInstallV2(
          await authority.install(prepared.scope, prepared.templateId, prepared.signal),
          prepared.scope.tenantId,
        ),
      );
    },
    seedTenantTemplates(input: DesktopTenantTemplatesSeedInputV2) {
      const prepared = prepareDesktopTenantTemplatesSeedV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantTemplateSeedV2(
          await authority.seed(prepared.scope, prepared.signal),
        ),
      );
    },
  });
}

export function createDesktopTenantTemplatesClientV2(
  operations: DesktopTenantTemplatesOperationsV2,
  config: DesktopRuntimeConfig,
): TemplatesRouteClient {
  const frozen = freezeDesktopTenantTemplatesConfigV2(config);
  return Object.freeze({
    observe: (scope, query, signal) =>
      operations.loadTenantTemplates({
        config: frozen,
        scope,
        ...(query === undefined ? {} : { query }),
        ...(signal === undefined ? {} : { signal }),
      }),
    get: (scope, templateId, signal) =>
      operations.getTenantTemplate({
        config: frozen,
        scope,
        templateId,
        ...(signal === undefined ? {} : { signal }),
      }),
    async install(scope, templateId, signal) {
      await operations.installTenantTemplate({
        config: frozen,
        scope,
        templateId,
        ...(signal === undefined ? {} : { signal }),
      });
    },
    seed: (scope, signal) =>
      operations.seedTenantTemplates({
        config: frozen,
        scope,
        ...(signal === undefined ? {} : { signal }),
      }),
  });
}

async function run<T>(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
  prepared: DesktopTenantTemplatesSeedInputV2,
  operation: (authority: DesktopTenantTemplatesAuthorityV2) => Promise<T>,
): Promise<T> {
  const actions = resolve();
  if (!actions) {
    throw new DesktopTenantTemplatesAuthorityUnavailableErrorV2({
      reasonCode: 'desktop_renderer_generation_actions_unavailable',
    });
  }
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantTemplatesAuthorityServiceV2>({
      service: DESKTOP_TENANT_TEMPLATES_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TENANT_TEMPLATES_AUTHORITY_VERSION_V2,
      scope: Object.freeze({ kind: 'tenant', tenant_id: prepared.scope.tenantId }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopTenantTemplatesAuthorityUnavailableErrorV2(admission);
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

function requireService(value: unknown): DesktopTenantTemplatesAuthorityServiceV2 {
  if (
    !record(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidService();
  }
  return value as unknown as DesktopTenantTemplatesAuthorityServiceV2;
}

function wrapAuthority(
  raw: unknown,
  active: () => boolean,
): DesktopTenantTemplatesAuthorityV2 {
  const methods = ['load', 'get', 'install', 'seed'] as const;
  if (
    !record(raw) ||
    Object.keys(raw).length !== methods.length ||
    methods.some((method) => typeof raw[method] !== 'function')
  ) {
    throw invalidService();
  }
  const authority = raw as unknown as DesktopTenantTemplatesAuthorityV2;
  const wrapped: DesktopTenantTemplatesAuthorityV2 = {
    load: (scope, query, signal) => invoke(active, authority.load, [scope, query, signal]),
    get: (scope, templateId, signal) =>
      invoke(active, authority.get, [scope, templateId, signal]),
    install: (scope, templateId, signal) =>
      invoke(active, authority.install, [scope, templateId, signal]),
    seed: (scope, signal) => invoke(active, authority.seed, [scope, signal]),
  };
  return Object.freeze(wrapped);
}

function invoke<TArgs extends readonly unknown[], TResult>(
  active: () => boolean,
  operation: (...args: TArgs) => TResult,
  args: TArgs,
): TResult {
  assertActive(active());
  return operation(...args);
}

function assertActive(active: boolean): void {
  if (!active) {
    throw new RuntimeV2Error(
      'desktop_tenant_templates_operation_released',
      'desktop tenant templates operation released',
    );
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalidService(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_templates_service_invalid',
    'desktop tenant templates authority service invalid',
  );
}

function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_TENANT_TEMPLATES_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry) {
    throw new RuntimeV2Error(
      'desktop_tenant_templates_authority_catalog_missing',
      'desktop tenant templates authority absent from catalog',
    );
  }
  return entry.contract_digest;
}
