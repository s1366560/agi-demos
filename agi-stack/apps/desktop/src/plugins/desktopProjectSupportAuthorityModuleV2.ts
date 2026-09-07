import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type { DesktopRuntimeConfig } from '../types';
import type {
  ProjectSupportClient,
  ProjectSupportCloseResult,
  ProjectSupportListSnapshot,
  ProjectSupportScope,
  ProjectSupportTicket,
} from '../features/project-support/projectSupportTypes';
import { createDesktopProjectSupportHttpAuthorityV2 } from './desktopProjectSupportHttpProjectionV2';
import {
  prepareDesktopProjectSupportOperationV2,
  type DesktopProjectSupportCloseInputV2,
  type DesktopProjectSupportCreateInputV2,
  type DesktopProjectSupportListInputV2,
  type DesktopProjectSupportOperationInputV2,
} from './desktopProjectSupportOperationContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_PROJECT_SUPPORT_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-support-authority';
export const DESKTOP_PROJECT_SUPPORT_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-support-authority';
export const DESKTOP_PROJECT_SUPPORT_AUTHORITY_VERSION_V2 = '1.0.0';
export interface DesktopProjectSupportAuthorityServiceV2 {
  readonly bindOperation: (config: DesktopRuntimeConfig) => ProjectSupportClient;
}
export interface DesktopProjectSupportOperationsV2 {
  readonly listSupportTickets: (
    input: DesktopProjectSupportListInputV2,
  ) => Promise<ProjectSupportListSnapshot>;
  readonly createSupportTicket: (
    input: DesktopProjectSupportCreateInputV2,
  ) => Promise<ProjectSupportTicket>;
  readonly closeSupportTicket: (
    input: DesktopProjectSupportCloseInputV2,
  ) => Promise<ProjectSupportCloseResult>;
}
type RejectionV2 =
  | Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }>
  | Readonly<{
      reasonCode: 'desktop_renderer_generation_actions_unavailable';
      runtimeCode?: undefined;
    }>;
export class DesktopProjectSupportAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: RejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;
  constructor(value: RejectionV2) {
    super(value.reasonCode);
    this.name = 'DesktopProjectSupportAuthorityUnavailableErrorV2';
    this.reasonCode = value.reasonCode;
    this.runtimeCode = value.runtimeCode;
  }
}

export function applyDesktopProjectSupportAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch')
    throw new RuntimeV2Error(
      'desktop_project_support_authority_config_invalid',
      'desktop project support authority requires desktop-api-fetch strategy',
    );
  context.provide(
    DESKTOP_PROJECT_SUPPORT_AUTHORITY_SERVICE_V2,
    Object.freeze({
      bindOperation: createDesktopProjectSupportHttpAuthorityV2,
    }),
  );
}
export const desktopProjectSupportAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PROJECT_SUPPORT_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigestV2(),
  apply: applyDesktopProjectSupportAuthorityV2,
});

export function createDesktopProjectSupportOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopProjectSupportOperationsV2 {
  const run = <T>(
    input: DesktopProjectSupportOperationInputV2,
    operation: (client: ProjectSupportClient) => Promise<T>,
  ) => runV2(resolveActions, input, operation);
  return Object.freeze({
    listSupportTickets(input: DesktopProjectSupportListInputV2) {
      const prepared = prepareDesktopProjectSupportOperationV2(input);
      return run(prepared, async (client) =>
        requireListV2(
          await client.list(prepared.scope, prepared.query, {
            signal: prepared.signal,
          }),
          prepared.scope,
        ),
      );
    },
    createSupportTicket(input: DesktopProjectSupportCreateInputV2) {
      const prepared = prepareDesktopProjectSupportOperationV2(input);
      return run(prepared, async (client) =>
        requireTicketV2(
          await client.create(prepared.scope, prepared.input, {
            signal: prepared.signal,
          }),
          prepared.scope,
        ),
      );
    },
    closeSupportTicket(input: DesktopProjectSupportCloseInputV2) {
      const prepared = prepareDesktopProjectSupportOperationV2(input);
      return run(prepared, async (client) =>
        requireCloseV2(
          await client.close(prepared.scope, prepared.ticketId, {
            signal: prepared.signal,
          }),
          prepared.ticketId,
        ),
      );
    },
  });
}
export function createDesktopProjectSupportClientV2(
  operations: DesktopProjectSupportOperationsV2,
  config: DesktopRuntimeConfig,
): ProjectSupportClient {
  const operationConfig = Object.freeze({ ...config });
  return Object.freeze({
    list: (scope, query, options) =>
      operations.listSupportTickets({
        config: operationConfig,
        scope,
        ...(query === undefined ? {} : { query }),
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      }),
    create: (scope, input, options) =>
      operations.createSupportTicket({
        config: operationConfig,
        scope,
        input,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      }),
    close: (scope, ticketId, options) =>
      operations.closeSupportTicket({
        config: operationConfig,
        scope,
        ticketId,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      }),
  });
}
async function runV2<T>(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
  input: DesktopProjectSupportOperationInputV2,
  operation: (client: ProjectSupportClient) => Promise<T>,
): Promise<T> {
  const prepared = prepareDesktopProjectSupportOperationV2(input);
  const actions = resolveActions();
  if (actions === null)
    throw new DesktopProjectSupportAuthorityUnavailableErrorV2({
      reasonCode: 'desktop_renderer_generation_actions_unavailable',
    });
  const admission =
    await actions.acquireServiceOperationLease<DesktopProjectSupportAuthorityServiceV2>({
      service: DESKTOP_PROJECT_SUPPORT_AUTHORITY_SERVICE_V2,
      version: DESKTOP_PROJECT_SUPPORT_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.scope.tenantId,
        project_id: prepared.scope.projectId,
      }),
    });
  if (admission.status === 'rejected')
    throw new DesktopProjectSupportAuthorityUnavailableErrorV2(admission);
  let failed = false;
  try {
    return await admission.useService((candidate) =>
      operation(requireClientV2(requireServiceV2(candidate).bindOperation(prepared.config))),
    );
  } catch (error) {
    failed = true;
    throw error;
  } finally {
    try {
      await admission.release();
    } catch (error) {
      if (!failed) throw error;
    }
  }
}
function requireServiceV2(value: unknown): DesktopProjectSupportAuthorityServiceV2 {
  if (
    !plainV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  )
    throw invalidServiceV2();
  return value as unknown as DesktopProjectSupportAuthorityServiceV2;
}
function requireClientV2(value: unknown): ProjectSupportClient {
  if (
    !plainV2(value) ||
    Object.keys(value).length !== 3 ||
    typeof value.list !== 'function' ||
    typeof value.create !== 'function' ||
    typeof value.close !== 'function'
  )
    throw invalidServiceV2();
  return value as unknown as ProjectSupportClient;
}
function plainV2(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === 'object' &&
    value !== null &&
    !Array.isArray(value) &&
    [Object.prototype, null].includes(Object.getPrototypeOf(value))
  );
}
function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_support_service_invalid',
    'desktop project support authority service is invalid',
  );
}
function requireListV2(value: unknown, scope: ProjectSupportScope): ProjectSupportListSnapshot {
  if (
    !plainV2(value) ||
    !sameScopeV2(value.scope, scope) ||
    value.authority !== scope.authority ||
    !Array.isArray(value.tickets) ||
    !value.tickets.every((ticket) => validTicketV2(ticket, scope)) ||
    !Number.isSafeInteger(value.total) ||
    Number(value.total) < 0 ||
    !Number.isSafeInteger(value.limit) ||
    Number(value.limit) < 1 ||
    !Number.isSafeInteger(value.offset) ||
    Number(value.offset) < 0 ||
    typeof value.hasMore !== 'boolean' ||
    !Array.isArray(value.allowedActions)
  )
    throw invalidResultV2();
  return deepFreezeV2(structuredClone(value)) as ProjectSupportListSnapshot;
}
function requireTicketV2(value: unknown, scope: ProjectSupportScope): ProjectSupportTicket {
  if (!validTicketV2(value, scope)) throw invalidResultV2();
  return deepFreezeV2(structuredClone(value)) as ProjectSupportTicket;
}
function requireCloseV2(value: unknown, ticketId: string): ProjectSupportCloseResult {
  if (
    !plainV2(value) ||
    Object.keys(value).length !== 3 ||
    value.id !== ticketId ||
    value.status !== 'closed' ||
    !canonicalTimestampV2(value.resolvedAt)
  )
    throw invalidResultV2();
  return Object.freeze({ ...value }) as ProjectSupportCloseResult;
}
function validTicketV2(value: unknown, scope: ProjectSupportScope): boolean {
  return (
    plainV2(value) &&
    value.tenantId === scope.tenantId &&
    typeof value.id === 'string' &&
    value.id.length > 0 &&
    typeof value.subject === 'string' &&
    typeof value.message === 'string' &&
    ['low', 'medium', 'high', 'urgent'].includes(String(value.priority)) &&
    ['open', 'in_progress', 'resolved', 'closed'].includes(String(value.status)) &&
    canonicalTimestampV2(value.createdAt) &&
    canonicalTimestampV2(value.updatedAt) &&
    (value.resolvedAt === null || canonicalTimestampV2(value.resolvedAt)) &&
    Array.isArray(value.allowedActions)
  );
}
function sameScopeV2(value: unknown, scope: ProjectSupportScope): boolean {
  return (
    plainV2(value) &&
    value.authority === scope.authority &&
    value.tenantId === scope.tenantId &&
    value.projectId === scope.projectId
  );
}
function canonicalTimestampV2(value: unknown): value is string {
  return typeof value === 'string' && value.trim() === value && !Number.isNaN(Date.parse(value));
}
function deepFreezeV2(value: unknown): unknown {
  if (typeof value !== 'object' || value === null) return value;
  for (const child of Object.values(value)) deepFreezeV2(child);
  return Object.freeze(value);
}
function invalidResultV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_support_service_contract_invalid',
    'desktop project support authority returned an invalid result',
  );
}
function generatedDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_PROJECT_SUPPORT_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry)
    throw new RuntimeV2Error(
      'desktop_project_support_authority_catalog_missing',
      'desktop project support authority is absent from generated catalog',
    );
  return entry.contract_digest;
}
