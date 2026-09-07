import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import { InstanceTemplatesUnavailableError } from '../features/instance-templates/instanceTemplatesClient';
import type {
  InstanceTemplateCreateInput,
  InstanceTemplateItem,
  InstanceTemplateSummary,
  InstanceTemplatesClient,
  InstanceTemplatesPage,
  InstanceTemplatesQuery,
  InstanceTemplatesRequestOptions,
  InstanceTemplatesScope,
} from '../features/instance-templates/instanceTemplatesTypes';
import type { DesktopRuntimeConfig } from '../types';
import { createDesktopInstanceTemplatesHttpProjectionV2 } from './desktopInstanceTemplatesHttpProjectionV2';
import {
  cloneDesktopInstanceTemplatesConfigV2,
  prepareDesktopInstanceTemplateCreateV2,
  prepareDesktopInstanceTemplatesBaseV2,
  prepareDesktopInstanceTemplatesIdV2,
  prepareDesktopInstanceTemplatesNameV2,
  prepareDesktopInstanceTemplatesQueryV2,
  type DesktopInstanceTemplatesBaseInputV2,
  type PreparedDesktopInstanceTemplatesBaseV2,
} from './desktopInstanceTemplatesOperationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_INSTANCE_TEMPLATES_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/instance-templates-authority';
export const DESKTOP_INSTANCE_TEMPLATES_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.instance-templates-authority';
export const DESKTOP_INSTANCE_TEMPLATES_AUTHORITY_VERSION_V2 = '1.0.0';

export const INSTANCE_TEMPLATES_CLOUD_ACTIONS_V2 = Object.freeze([
  'view',
  'list',
  'list-items',
  'create',
  'delete',
  'publish',
  'clone',
  'refresh',
  'paginate',
  'search-current-page',
  'filter-status',
]);

export type DesktopInstanceTemplatesCapabilityV2 = Readonly<{
  availability: 'available' | 'not_applicable';
  reasonCode: string | null;
  allowedActions: readonly string[];
  authorityRevision: number | null;
}>;

export interface DesktopInstanceTemplatesAuthorityV2 {
  list(
    query: InstanceTemplatesQuery,
    signal?: AbortSignal,
  ): Promise<InstanceTemplatesPage>;
  get(id: string, signal?: AbortSignal): Promise<InstanceTemplateSummary>;
  listItems(
    id: string,
    signal?: AbortSignal,
  ): Promise<readonly InstanceTemplateItem[]>;
  create(
    input: InstanceTemplateCreateInput,
    signal?: AbortSignal,
  ): Promise<InstanceTemplateSummary>;
  delete(id: string, signal?: AbortSignal): Promise<void>;
  publish(id: string, signal?: AbortSignal): Promise<InstanceTemplateSummary>;
  clone(
    id: string,
    newName: string,
    signal?: AbortSignal,
  ): Promise<InstanceTemplateSummary>;
  probe(signal?: AbortSignal): Promise<DesktopInstanceTemplatesCapabilityV2>;
}

export interface DesktopInstanceTemplatesAuthorityServiceV2 {
  bindOperation(
    config: DesktopRuntimeConfig,
    scope: InstanceTemplatesScope,
  ): DesktopInstanceTemplatesAuthorityV2;
}

type IdInput = DesktopInstanceTemplatesBaseInputV2 & Readonly<{ id: string }>;
type CreateInput = DesktopInstanceTemplatesBaseInputV2 &
  Readonly<{ input: InstanceTemplateCreateInput }>;
type CloneInput = IdInput & Readonly<{ newName: string }>;

export interface DesktopInstanceTemplatesOperationsV2 {
  list(
    input: DesktopInstanceTemplatesBaseInputV2 &
      Readonly<{ query?: InstanceTemplatesQuery }>,
  ): Promise<InstanceTemplatesPage>;
  get(input: IdInput): Promise<InstanceTemplateSummary>;
  listItems(input: IdInput): Promise<readonly InstanceTemplateItem[]>;
  create(input: CreateInput): Promise<InstanceTemplateSummary>;
  delete(input: IdInput): Promise<void>;
  publish(input: IdInput): Promise<InstanceTemplateSummary>;
  clone(input: CloneInput): Promise<InstanceTemplateSummary>;
  probe(
    input: DesktopInstanceTemplatesBaseInputV2,
  ): Promise<DesktopInstanceTemplatesCapabilityV2>;
}

type Rejection =
  | Extract<
      DesktopRendererServiceOperationLeaseAdmissionV2<never>,
      { status: 'rejected' }
    >
  | Readonly<{
      reasonCode: 'desktop_renderer_generation_actions_unavailable';
      runtimeCode?: undefined;
    }>;

export class DesktopInstanceTemplatesAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: Rejection['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: Rejection) {
    super(rejection.reasonCode);
    this.name = 'DesktopInstanceTemplatesAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopInstanceTemplatesAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (
    Object.keys(config).length !== 1 ||
    config.strategy !== 'desktop-vault-broker'
  ) {
    throw new RuntimeV2Error(
      'desktop_instance_templates_authority_config_invalid',
      'desktop instance templates authority requires desktop-vault-broker strategy',
    );
  }
  context.provide(
    DESKTOP_INSTANCE_TEMPLATES_AUTHORITY_SERVICE_V2,
    Object.freeze({
      bindOperation(
        configValue: DesktopRuntimeConfig,
        scope: InstanceTemplatesScope,
      ) {
        return bind(
          createDesktopInstanceTemplatesHttpProjectionV2(configValue),
          scope,
        );
      },
    }),
  );
}

export const desktopInstanceTemplatesAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_INSTANCE_TEMPLATES_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedDigest(),
    apply: applyDesktopInstanceTemplatesAuthorityV2,
  });

export function createDesktopInstanceTemplatesOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopInstanceTemplatesOperationsV2 {
  const execute = <T>(
    input: DesktopInstanceTemplatesBaseInputV2,
    callback: (
      authority: DesktopInstanceTemplatesAuthorityV2,
      base: PreparedDesktopInstanceTemplatesBaseV2,
    ) => Promise<T>,
  ) =>
    run(
      requireActions(resolve()),
      prepareDesktopInstanceTemplatesBaseV2(input),
      callback,
    );

  const operations: DesktopInstanceTemplatesOperationsV2 = {
    list(input) {
      const query = prepareDesktopInstanceTemplatesQueryV2(input.query);
      return execute(input, (authority, base) =>
        authority.list(query, base.signal),
      );
    },
    get(input) {
      const id = prepareDesktopInstanceTemplatesIdV2(input.id);
      return execute(input, (authority, base) =>
        authority.get(id, base.signal),
      );
    },
    listItems(input) {
      const id = prepareDesktopInstanceTemplatesIdV2(input.id);
      return execute(input, (authority, base) =>
        authority.listItems(id, base.signal),
      );
    },
    create(input) {
      const value = prepareDesktopInstanceTemplateCreateV2(input.input);
      return execute(input, (authority, base) =>
        authority.create(value, base.signal),
      );
    },
    delete(input) {
      const id = prepareDesktopInstanceTemplatesIdV2(input.id);
      return execute(input, (authority, base) =>
        authority.delete(id, base.signal),
      );
    },
    publish(input) {
      const id = prepareDesktopInstanceTemplatesIdV2(input.id);
      return execute(input, (authority, base) =>
        authority.publish(id, base.signal),
      );
    },
    clone(input) {
      const id = prepareDesktopInstanceTemplatesIdV2(input.id);
      const name = prepareDesktopInstanceTemplatesNameV2(input.newName);
      return execute(input, (authority, base) =>
        authority.clone(id, name, base.signal),
      );
    },
    probe(input) {
      return execute(input, (authority, base) => authority.probe(base.signal));
    },
  };
  return Object.freeze(operations);
}

export function createDesktopInstanceTemplatesClientV2(
  operations: DesktopInstanceTemplatesOperationsV2,
  config: DesktopRuntimeConfig,
): InstanceTemplatesClient {
  const frozenConfig = cloneDesktopInstanceTemplatesConfigV2(config);
  const base = (
    scope: InstanceTemplatesScope,
    options?: InstanceTemplatesRequestOptions,
  ) => ({
    config: frozenConfig,
    scope,
    ...(options?.signal === undefined ? {} : { signal: options.signal }),
  });
  const client: InstanceTemplatesClient = {
    list: (scope, query, options) =>
      operations.list({
        ...base(scope, options),
        ...(query === undefined ? {} : { query }),
      }),
    get: (scope, id, options) =>
      operations.get({ ...base(scope, options), id }),
    listItems: (scope, id, options) =>
      operations.listItems({ ...base(scope, options), id }),
    create: (scope, input, options) =>
      operations.create({ ...base(scope, options), input }),
    delete: (scope, id, options) =>
      operations.delete({ ...base(scope, options), id }),
    publish: (scope, id, options) =>
      operations.publish({ ...base(scope, options), id }),
    clone: (scope, id, newName, options) =>
      operations.clone({ ...base(scope, options), id, newName }),
  };
  return Object.freeze(client);
}

export function withDesktopInstanceTemplatesAuthorityOperationV2<T>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopInstanceTemplatesBaseInputV2,
  callback: (
    authority: DesktopInstanceTemplatesAuthorityV2,
    base: PreparedDesktopInstanceTemplatesBaseV2,
  ) => Promise<T>,
): Promise<T> {
  return run(actions, prepareDesktopInstanceTemplatesBaseV2(input), callback);
}

async function run<T>(
  actions: DesktopRendererGenerationActionsV2,
  base: PreparedDesktopInstanceTemplatesBaseV2,
  callback: (
    authority: DesktopInstanceTemplatesAuthorityV2,
    base: PreparedDesktopInstanceTemplatesBaseV2,
  ) => Promise<T>,
): Promise<T> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopInstanceTemplatesAuthorityServiceV2>(
      {
        service: DESKTOP_INSTANCE_TEMPLATES_AUTHORITY_SERVICE_V2,
        version: DESKTOP_INSTANCE_TEMPLATES_AUTHORITY_VERSION_V2,
        scope: Object.freeze({
          kind: 'tenant',
          tenant_id: base.scope.tenantId,
        }),
      },
    );
  if (admission.status === 'rejected') {
    throw new DesktopInstanceTemplatesAuthorityUnavailableErrorV2(admission);
  }
  let operationFailed = false;
  let active = true;
  try {
    return await admission.useService((candidate) =>
      callback(
        revocable(
          requireAuthority(
            requireService(candidate).bindOperation(base.config, base.scope),
          ),
          () => active,
        ),
        base,
      ),
    );
  } catch (error) {
    operationFailed = true;
    throw error;
  } finally {
    active = false;
    try {
      await admission.release();
    } catch (error) {
      if (!operationFailed) throw error;
    }
  }
}

function bind(
  client: InstanceTemplatesClient,
  scope: InstanceTemplatesScope,
): DesktopInstanceTemplatesAuthorityV2 {
  const bound: DesktopInstanceTemplatesAuthorityV2 = {
    list: (query, signal) => client.list(scope, query, signalOptions(signal)),
    get: (id, signal) => client.get(scope, id, signalOptions(signal)),
    listItems: (id, signal) =>
      client.listItems(scope, id, signalOptions(signal)),
    create: (input, signal) =>
      client.create(scope, input, signalOptions(signal)),
    delete: (id, signal) => client.delete(scope, id, signalOptions(signal)),
    publish: (id, signal) => client.publish(scope, id, signalOptions(signal)),
    clone: (id, newName, signal) =>
      client.clone(scope, id, newName, signalOptions(signal)),
    async probe(signal) {
      try {
        await client.list(
          scope,
          { page: 1, pageSize: 1 },
          signalOptions(signal),
        );
        return Object.freeze({
          availability: 'available' as const,
          reasonCode: 'instance_templates_nested_deep_link_and_deploy_partial',
          allowedActions: INSTANCE_TEMPLATES_CLOUD_ACTIONS_V2,
          authorityRevision: null,
        });
      } catch (error) {
        if (
          error instanceof InstanceTemplatesUnavailableError &&
          error.reasonCode === 'local_instance_template_authority_unavailable'
        ) {
          return Object.freeze({
            availability: 'not_applicable' as const,
            reasonCode: error.reasonCode,
            allowedActions: Object.freeze([]),
            authorityRevision: null,
          });
        }
        throw error;
      }
    },
  };
  return Object.freeze(bound);
}

function revocable(
  authority: DesktopInstanceTemplatesAuthorityV2,
  active: () => boolean,
): DesktopInstanceTemplatesAuthorityV2 {
  const invoke = async <T>(operation: () => Promise<T>): Promise<T> => {
    assertActive(active);
    const result = await operation();
    assertActive(active);
    return result;
  };
  const wrapped: DesktopInstanceTemplatesAuthorityV2 = {
    list: (query, signal) => invoke(() => authority.list(query, signal)),
    get: (id, signal) => invoke(() => authority.get(id, signal)),
    listItems: (id, signal) => invoke(() => authority.listItems(id, signal)),
    create: (input, signal) => invoke(() => authority.create(input, signal)),
    delete: (id, signal) => invoke(() => authority.delete(id, signal)),
    publish: (id, signal) => invoke(() => authority.publish(id, signal)),
    clone: (id, name, signal) =>
      invoke(() => authority.clone(id, name, signal)),
    probe: (signal) => invoke(() => authority.probe(signal)),
  };
  return Object.freeze(wrapped);
}

function requireService(
  value: unknown,
): DesktopInstanceTemplatesAuthorityServiceV2 {
  if (
    !isRecord(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidService();
  }
  return value as unknown as DesktopInstanceTemplatesAuthorityServiceV2;
}

function requireAuthority(value: unknown): DesktopInstanceTemplatesAuthorityV2 {
  const keys = [
    'list',
    'get',
    'listItems',
    'create',
    'delete',
    'publish',
    'clone',
    'probe',
  ];
  if (
    !isRecord(value) ||
    Object.keys(value).length !== keys.length ||
    keys.some((key) => typeof value[key] !== 'function')
  ) {
    throw invalidService();
  }
  return value as unknown as DesktopInstanceTemplatesAuthorityV2;
}

function requireActions(
  value: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (value) return value;
  throw new DesktopInstanceTemplatesAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function signalOptions(
  signal: AbortSignal | undefined,
): InstanceTemplatesRequestOptions | undefined {
  return signal === undefined ? undefined : Object.freeze({ signal });
}

function assertActive(active: () => boolean): void {
  if (!active()) {
    throw new RuntimeV2Error(
      'desktop_instance_templates_operation_released',
      'desktop instance templates operation released',
    );
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalidService(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_instance_templates_service_invalid',
    'desktop instance templates authority service invalid',
  );
}

function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) =>
      candidate.module_ref ===
      DESKTOP_INSTANCE_TEMPLATES_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry) {
    throw new RuntimeV2Error(
      'desktop_instance_templates_authority_catalog_missing',
      'desktop instance templates authority absent from catalog',
    );
  }
  return entry.contract_digest;
}
