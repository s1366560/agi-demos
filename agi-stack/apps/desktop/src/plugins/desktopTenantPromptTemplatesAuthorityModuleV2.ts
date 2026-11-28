import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  DesktopRuntimeConfig,
  PromptTemplateCreateInput,
  PromptTemplateRecord,
} from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import { createDesktopTenantPromptTemplatesHttpProjectionV2 } from './desktopTenantPromptTemplatesHttpProjectionV2';
import {
  freezeDesktopTenantPromptTemplatesConfigV2,
  prepareDesktopTenantPromptTemplatesCreateV2,
  prepareDesktopTenantPromptTemplatesDeleteV2,
  prepareDesktopTenantPromptTemplatesLoadV2,
  requireDesktopTenantPromptTemplateDeleteV2,
  requireDesktopTenantPromptTemplatesV2,
  requireDesktopTenantPromptTemplateV2,
  type DesktopTenantPromptTemplatesAuthorityV2,
  type DesktopTenantPromptTemplatesCreateInputV2,
  type DesktopTenantPromptTemplatesDeleteInputV2,
  type DesktopTenantPromptTemplatesLoadInputV2,
  type DesktopTenantPromptTemplatesScopeV2,
} from './desktopTenantPromptTemplatesOperationContractV2';

export const DESKTOP_TENANT_PROMPT_TEMPLATES_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-prompt-templates-authority';
export const DESKTOP_TENANT_PROMPT_TEMPLATES_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-prompt-templates-authority';
export const DESKTOP_TENANT_PROMPT_TEMPLATES_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopTenantPromptTemplatesAuthorityServiceV2 {
  bindOperation(
    config: DesktopRuntimeConfig,
    scope: DesktopTenantPromptTemplatesScopeV2,
  ): DesktopTenantPromptTemplatesAuthorityV2;
}

export interface DesktopTenantPromptTemplatesOperationsV2 {
  listTenantPromptTemplates(
    input: DesktopTenantPromptTemplatesLoadInputV2,
  ): Promise<readonly PromptTemplateRecord[]>;
  createTenantPromptTemplate(
    input: DesktopTenantPromptTemplatesCreateInputV2,
  ): Promise<PromptTemplateRecord>;
  deleteTenantPromptTemplate(input: DesktopTenantPromptTemplatesDeleteInputV2): Promise<void>;
}

export interface DesktopTenantPromptTemplatesClientV2 {
  listPromptTemplates(
    tenantId: string,
    signal?: AbortSignal,
  ): Promise<PromptTemplateRecord[]>;
  createPromptTemplate(
    tenantId: string,
    input: PromptTemplateCreateInput,
    signal?: AbortSignal,
  ): Promise<PromptTemplateRecord>;
  deletePromptTemplate(
    templateId: string,
    signal?: AbortSignal,
    expectedRevision?: number,
  ): Promise<void>;
}

type Rejection =
  | Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }>
  | Readonly<{
      reasonCode: 'desktop_renderer_generation_actions_unavailable';
      runtimeCode?: undefined;
    }>;

export class DesktopTenantPromptTemplatesAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: Rejection['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: Rejection) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantPromptTemplatesAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTenantPromptTemplatesAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_tenant_prompt_templates_authority_config_invalid',
      'desktop tenant prompt templates authority requires desktop-api-fetch strategy',
    );
  }
  context.provide(
    DESKTOP_TENANT_PROMPT_TEMPLATES_AUTHORITY_SERVICE_V2,
    Object.freeze({
      bindOperation(configValue: DesktopRuntimeConfig) {
        return createDesktopTenantPromptTemplatesHttpProjectionV2(configValue);
      },
    }),
  );
}

export const desktopTenantPromptTemplatesAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_TENANT_PROMPT_TEMPLATES_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedDigest(),
    apply: applyDesktopTenantPromptTemplatesAuthorityV2,
  });

export function createDesktopTenantPromptTemplatesOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopTenantPromptTemplatesOperationsV2 {
  return Object.freeze({
    listTenantPromptTemplates(input: DesktopTenantPromptTemplatesLoadInputV2) {
      const prepared = prepareDesktopTenantPromptTemplatesLoadV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantPromptTemplatesV2(
          await authority.list(prepared.scope, prepared.signal),
          prepared.scope.tenantId,
        ),
      );
    },
    createTenantPromptTemplate(input: DesktopTenantPromptTemplatesCreateInputV2) {
      const prepared = prepareDesktopTenantPromptTemplatesCreateV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantPromptTemplateV2(
          await authority.create(prepared.scope, prepared.input, prepared.signal),
          prepared.scope.tenantId,
          prepared.input,
        ),
      );
    },
    deleteTenantPromptTemplate(input: DesktopTenantPromptTemplatesDeleteInputV2) {
      const prepared = prepareDesktopTenantPromptTemplatesDeleteV2(input);
      return run(resolve, prepared, async (authority) =>
        requireDesktopTenantPromptTemplateDeleteV2(
          await authority.delete(
            prepared.scope,
            prepared.templateId,
            prepared.expectedRevision,
            prepared.signal,
          ),
        ),
      );
    },
  });
}

export function createDesktopTenantPromptTemplatesClientV2(
  operations: DesktopTenantPromptTemplatesOperationsV2,
  config: DesktopRuntimeConfig,
): DesktopTenantPromptTemplatesClientV2 {
  const frozen = freezeDesktopTenantPromptTemplatesConfigV2(config);
  const scope = Object.freeze({ authority: frozen.mode, tenantId: frozen.tenantId });
  const client: DesktopTenantPromptTemplatesClientV2 = {
    async listPromptTemplates(tenantId: string, signal?: AbortSignal) {
      requireClientTenant(tenantId, frozen.tenantId);
      return [
        ...(await operations.listTenantPromptTemplates({
          config: frozen,
          scope,
          ...(signal === undefined ? {} : { signal }),
        })),
      ];
    },
    createPromptTemplate(
      tenantId: string,
      input: PromptTemplateCreateInput,
      signal?: AbortSignal,
    ) {
      requireClientTenant(tenantId, frozen.tenantId);
      return operations.createTenantPromptTemplate({
        config: frozen,
        scope,
        input,
        ...(signal === undefined ? {} : { signal }),
      });
    },
    deletePromptTemplate(
      templateId: string,
      signal?: AbortSignal,
      expectedRevision?: number,
    ) {
      return operations.deleteTenantPromptTemplate({
        config: frozen,
        scope,
        templateId,
        ...(expectedRevision === undefined ? {} : { expectedRevision }),
        ...(signal === undefined ? {} : { signal }),
      });
    },
  };
  return Object.freeze(client);
}

async function run<T>(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
  prepared: DesktopTenantPromptTemplatesLoadInputV2,
  operation: (authority: DesktopTenantPromptTemplatesAuthorityV2) => Promise<T>,
): Promise<T> {
  const actions = resolve();
  if (!actions) {
    throw new DesktopTenantPromptTemplatesAuthorityUnavailableErrorV2({
      reasonCode: 'desktop_renderer_generation_actions_unavailable',
    });
  }
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantPromptTemplatesAuthorityServiceV2>({
      service: DESKTOP_TENANT_PROMPT_TEMPLATES_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TENANT_PROMPT_TEMPLATES_AUTHORITY_VERSION_V2,
      scope: Object.freeze({ kind: 'tenant', tenant_id: prepared.scope.tenantId }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopTenantPromptTemplatesAuthorityUnavailableErrorV2(admission);
  }
  let failed = false;
  let active = true;
  try {
    return await admission.useService(async (candidate) => {
      assertActive(active);
      const service = requireService(candidate);
      const raw = service.bindOperation(prepared.config, prepared.scope);
      const result = await operation(wrapAuthority(raw, () => active));
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

function requireService(value: unknown): DesktopTenantPromptTemplatesAuthorityServiceV2 {
  if (!record(value) || Object.keys(value).length !== 1 || typeof value.bindOperation !== 'function') {
    throw invalidService();
  }
  return value as unknown as DesktopTenantPromptTemplatesAuthorityServiceV2;
}

function wrapAuthority(
  raw: unknown,
  active: () => boolean,
): DesktopTenantPromptTemplatesAuthorityV2 {
  const methods = ['list', 'create', 'delete'] as const;
  if (
    !record(raw) ||
    Object.keys(raw).length !== methods.length ||
    methods.some((method) => typeof raw[method] !== 'function')
  ) {
    throw invalidService();
  }
  const authority = raw as unknown as DesktopTenantPromptTemplatesAuthorityV2;
  const wrapped: DesktopTenantPromptTemplatesAuthorityV2 = {
    list: (scope: DesktopTenantPromptTemplatesScopeV2, signal?: AbortSignal) =>
      invoke(active, authority.list, [scope, signal]),
    create: (
      scope: DesktopTenantPromptTemplatesScopeV2,
      input: PromptTemplateCreateInput,
      signal?: AbortSignal,
    ) => invoke(active, authority.create, [scope, input, signal]),
    delete: (
      scope: DesktopTenantPromptTemplatesScopeV2,
      id: string,
      revision?: number,
      signal?: AbortSignal,
    ) =>
      invoke(active, authority.delete, [scope, id, revision, signal]),
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

function requireClientTenant(value: string, expected: string): void {
  if (value !== expected) {
    throw new RuntimeV2Error(
      'desktop_tenant_prompt_templates_operation_input_invalid',
      'desktop tenant prompt templates tenant scope invalid',
    );
  }
}

function assertActive(active: boolean): void {
  if (!active) {
    throw new RuntimeV2Error(
      'desktop_tenant_prompt_templates_operation_released',
      'desktop tenant prompt templates operation released',
    );
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalidService(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_prompt_templates_service_invalid',
    'desktop tenant prompt templates authority service invalid',
  );
}

function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_TENANT_PROMPT_TEMPLATES_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry) {
    throw new RuntimeV2Error(
      'desktop_tenant_prompt_templates_authority_catalog_missing',
      'desktop tenant prompt templates authority absent from catalog',
    );
  }
  return entry.contract_digest;
}
