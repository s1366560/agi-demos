import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import { DesktopApiClient, type WorkspaceMemberRole } from '../api/client';
import type { DesktopRuntimeConfig, WorkspaceMemberSummary } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import {
  assertVoidWorkspaceMemberMutationResponseV2,
  assertWorkspaceMemberMutationSignalV2,
  cloneWorkspaceMemberMutationResponseV2,
  cloneWorkspaceMemberMutationRoleV2,
  cloneWorkspaceMemberMutationRuntimeConfigV2,
  cloneWorkspaceMemberMutationSignalV2,
  cloneWorkspaceMemberMutationUserIdV2,
  cloneWorkspaceMemberMutationWorkspaceIdV2,
  hasExactOptionalKeysV2,
  isPlainRecordV2,
  workspaceMemberMutationInputInvalidV2,
} from './desktopWorkspaceMemberMutationContractV2';

export const DESKTOP_WORKSPACE_MEMBER_MUTATION_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/workspace-member-mutation-authority';
export const DESKTOP_WORKSPACE_MEMBER_MUTATION_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.workspace-member-mutation-authority';
export const DESKTOP_WORKSPACE_MEMBER_MUTATION_AUTHORITY_VERSION_V2 = '1.0.0';

export type DesktopWorkspaceMemberMutationWithRoleInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  workspaceId: string;
  userId: string;
  role: WorkspaceMemberRole;
  signal?: AbortSignal;
}>;

export type DesktopWorkspaceMemberMutationRemoveInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  workspaceId: string;
  userId: string;
  signal?: AbortSignal;
}>;

export interface DesktopWorkspaceMemberMutationAuthorityV2 {
  readonly addMember: (
    userId: string,
    role: WorkspaceMemberRole,
    signal?: AbortSignal,
  ) => Promise<WorkspaceMemberSummary>;
  readonly updateMemberRole: (
    userId: string,
    role: WorkspaceMemberRole,
    signal?: AbortSignal,
  ) => Promise<WorkspaceMemberSummary>;
  readonly removeMember: (userId: string, signal?: AbortSignal) => Promise<void>;
}

export interface DesktopWorkspaceMemberMutationAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    workspaceId: string,
  ) => DesktopWorkspaceMemberMutationAuthorityV2;
}

export interface DesktopWorkspaceMemberMutationOperationsV2 {
  readonly addWorkspaceMember: (
    input: DesktopWorkspaceMemberMutationWithRoleInputV2,
  ) => Promise<WorkspaceMemberSummary>;
  readonly updateWorkspaceMemberRole: (
    input: DesktopWorkspaceMemberMutationWithRoleInputV2,
  ) => Promise<WorkspaceMemberSummary>;
  readonly removeWorkspaceMember: (
    input: DesktopWorkspaceMemberMutationRemoveInputV2,
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

type AuthorityAdmissionRejectionV2 = ServiceAdmissionRejectionV2 | GenerationActionsUnavailableV2;

type PreparedWorkspaceMemberMutationV2 = Readonly<{
  kind: 'add' | 'update-role' | 'remove';
  config: DesktopRuntimeConfig;
  workspaceId: string;
  userId: string;
  role?: WorkspaceMemberRole;
  signal?: AbortSignal;
}>;

const WITH_ROLE_INPUT_KEYS_V2 = new Set(['config', 'role', 'signal', 'userId', 'workspaceId']);
const REMOVE_INPUT_KEYS_V2 = new Set(['config', 'signal', 'userId', 'workspaceId']);
const AUTHORITY_KEYS_V2 = new Set(['addMember', 'removeMember', 'updateMemberRole']);

export class DesktopWorkspaceMemberMutationAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopWorkspaceMemberMutationAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopWorkspaceMemberMutationAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_workspace_member_mutation_authority_config_invalid',
      'desktop workspace-member mutation authority requires desktop-api-client strategy',
    );
  }
  const service: DesktopWorkspaceMemberMutationAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopWorkspaceMemberMutationAuthorityV2,
  });
  context.provide(DESKTOP_WORKSPACE_MEMBER_MUTATION_AUTHORITY_SERVICE_V2, service);
}

export const desktopWorkspaceMemberMutationAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_WORKSPACE_MEMBER_MUTATION_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedContractDigestV2(),
    apply: applyDesktopWorkspaceMemberMutationAuthorityV2,
  });

export function createDesktopWorkspaceMemberMutationOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopWorkspaceMemberMutationOperationsV2 {
  return Object.freeze({
    addWorkspaceMember(input: DesktopWorkspaceMemberMutationWithRoleInputV2) {
      const prepared = prepareWorkspaceMemberMutationWithRoleV2('add', input);
      return runDesktopWorkspaceMemberMutationAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.addMember(prepared.userId, requirePreparedRoleV2(prepared), prepared.signal),
      );
    },
    updateWorkspaceMemberRole(input: DesktopWorkspaceMemberMutationWithRoleInputV2) {
      const prepared = prepareWorkspaceMemberMutationWithRoleV2('update-role', input);
      return runDesktopWorkspaceMemberMutationAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) =>
          authority.updateMemberRole(
            prepared.userId,
            requirePreparedRoleV2(prepared),
            prepared.signal,
          ),
      );
    },
    removeWorkspaceMember(input: DesktopWorkspaceMemberMutationRemoveInputV2) {
      const prepared = prepareWorkspaceMemberMutationRemoveV2(input);
      return runDesktopWorkspaceMemberMutationAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.removeMember(prepared.userId, prepared.signal),
      );
    },
  });
}

export function withDesktopWorkspaceMemberMutationAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopWorkspaceMemberMutationWithRoleInputV2,
  operation: (
    authority: DesktopWorkspaceMemberMutationAuthorityV2,
    prepared: PreparedWorkspaceMemberMutationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopWorkspaceMemberMutationAuthorityOperationV2(
    actions,
    prepareWorkspaceMemberMutationWithRoleV2('add', input),
    operation,
  );
}

async function runDesktopWorkspaceMemberMutationAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedWorkspaceMemberMutationV2,
  operation: (
    authority: DesktopWorkspaceMemberMutationAuthorityV2,
    prepared: PreparedWorkspaceMemberMutationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopWorkspaceMemberMutationAuthorityServiceV2>({
      service: DESKTOP_WORKSPACE_MEMBER_MUTATION_AUTHORITY_SERVICE_V2,
      version: DESKTOP_WORKSPACE_MEMBER_MUTATION_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'project',
        tenant_id: prepared.config.tenantId,
        project_id: prepared.config.projectId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopWorkspaceMemberMutationAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireWorkspaceMemberMutationServiceV2(candidate);
      const authority = requireWorkspaceMemberMutationAuthorityV2(
        service.bindOperation(prepared.config, prepared.workspaceId),
      );
      return operation(
        createRevocableWorkspaceMemberMutationAuthorityV2(
          authority,
          prepared,
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

function createDesktopWorkspaceMemberMutationAuthorityV2(
  config: DesktopRuntimeConfig,
  workspaceId: string,
): DesktopWorkspaceMemberMutationAuthorityV2 {
  const operationConfig = cloneWorkspaceMemberMutationRuntimeConfigV2(config);
  const operationWorkspaceId = cloneWorkspaceMemberMutationWorkspaceIdV2(
    operationConfig,
    workspaceId,
  );
  const transport = new DesktopApiClient(operationConfig);
  return Object.freeze({
    addMember(userId: string, role: WorkspaceMemberRole, signal?: AbortSignal) {
      const operationUserId = cloneWorkspaceMemberMutationUserIdV2(userId);
      const operationRole = cloneWorkspaceMemberMutationRoleV2(role);
      const operationSignal = cloneWorkspaceMemberMutationSignalV2(signal);
      return transport
        .addWorkspaceMemberForProject(
          operationConfig.projectId,
          operationWorkspaceId,
          operationUserId,
          operationRole,
          operationConfig.tenantId,
          operationSignal,
        )
        .then((value) =>
          cloneWorkspaceMemberMutationResponseV2(
            value,
            operationWorkspaceId,
            operationUserId,
            operationRole,
          ),
        );
    },
    updateMemberRole(userId: string, role: WorkspaceMemberRole, signal?: AbortSignal) {
      const operationUserId = cloneWorkspaceMemberMutationUserIdV2(userId);
      const operationRole = cloneWorkspaceMemberMutationRoleV2(role);
      const operationSignal = cloneWorkspaceMemberMutationSignalV2(signal);
      return transport
        .updateWorkspaceMemberRoleForProject(
          operationConfig.projectId,
          operationWorkspaceId,
          operationUserId,
          operationRole,
          operationConfig.tenantId,
          operationSignal,
        )
        .then((value) =>
          cloneWorkspaceMemberMutationResponseV2(
            value,
            operationWorkspaceId,
            operationUserId,
            operationRole,
          ),
        );
    },
    removeMember(userId: string, signal?: AbortSignal) {
      const operationUserId = cloneWorkspaceMemberMutationUserIdV2(userId);
      const operationSignal = cloneWorkspaceMemberMutationSignalV2(signal);
      return transport
        .removeWorkspaceMemberForProject(
          operationConfig.projectId,
          operationWorkspaceId,
          operationUserId,
          operationConfig.tenantId,
          operationSignal,
        )
        .then(assertVoidWorkspaceMemberMutationResponseV2);
    },
  });
}

function createRevocableWorkspaceMemberMutationAuthorityV2(
  authority: DesktopWorkspaceMemberMutationAuthorityV2,
  expected: PreparedWorkspaceMemberMutationV2,
  isOperationActive: () => boolean,
): DesktopWorkspaceMemberMutationAuthorityV2 {
  return Object.freeze({
    addMember(userId: string, role: WorkspaceMemberRole, signal?: AbortSignal) {
      assertWorkspaceMemberMutationOperationV2('add', expected, isOperationActive);
      const operationUserId = cloneWorkspaceMemberMutationUserIdV2(userId);
      const operationRole = cloneWorkspaceMemberMutationRoleV2(role);
      const operationSignal = cloneWorkspaceMemberMutationSignalV2(signal);
      assertExpectedWorkspaceMemberMutationInputV2(
        expected,
        operationUserId,
        operationRole,
        operationSignal,
      );
      return Promise.resolve(
        authority.addMember(operationUserId, operationRole, operationSignal),
      ).then((value) =>
        cloneWorkspaceMemberMutationResponseV2(
          value,
          expected.workspaceId,
          operationUserId,
          operationRole,
        ),
      );
    },
    updateMemberRole(userId: string, role: WorkspaceMemberRole, signal?: AbortSignal) {
      assertWorkspaceMemberMutationOperationV2('update-role', expected, isOperationActive);
      const operationUserId = cloneWorkspaceMemberMutationUserIdV2(userId);
      const operationRole = cloneWorkspaceMemberMutationRoleV2(role);
      const operationSignal = cloneWorkspaceMemberMutationSignalV2(signal);
      assertExpectedWorkspaceMemberMutationInputV2(
        expected,
        operationUserId,
        operationRole,
        operationSignal,
      );
      return Promise.resolve(
        authority.updateMemberRole(operationUserId, operationRole, operationSignal),
      ).then((value) =>
        cloneWorkspaceMemberMutationResponseV2(
          value,
          expected.workspaceId,
          operationUserId,
          operationRole,
        ),
      );
    },
    removeMember(userId: string, signal?: AbortSignal) {
      assertWorkspaceMemberMutationOperationV2('remove', expected, isOperationActive);
      const operationUserId = cloneWorkspaceMemberMutationUserIdV2(userId);
      const operationSignal = cloneWorkspaceMemberMutationSignalV2(signal);
      assertExpectedWorkspaceMemberMutationInputV2(
        expected,
        operationUserId,
        undefined,
        operationSignal,
      );
      return Promise.resolve(authority.removeMember(operationUserId, operationSignal)).then(
        assertVoidWorkspaceMemberMutationResponseV2,
      );
    },
  });
}

function prepareWorkspaceMemberMutationWithRoleV2(
  kind: 'add' | 'update-role',
  input: DesktopWorkspaceMemberMutationWithRoleInputV2,
): PreparedWorkspaceMemberMutationV2 {
  if (
    !isPlainRecordV2(input) ||
    !hasExactOptionalKeysV2(input, WITH_ROLE_INPUT_KEYS_V2) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'workspaceId') ||
    !Object.hasOwn(input, 'userId') ||
    !Object.hasOwn(input, 'role')
  ) {
    throw workspaceMemberMutationInputInvalidV2();
  }
  const config = cloneWorkspaceMemberMutationRuntimeConfigV2(input.config);
  return Object.freeze({
    kind,
    config,
    workspaceId: cloneWorkspaceMemberMutationWorkspaceIdV2(config, input.workspaceId),
    userId: cloneWorkspaceMemberMutationUserIdV2(input.userId),
    role: cloneWorkspaceMemberMutationRoleV2(input.role),
    ...(input.signal === undefined
      ? {}
      : { signal: cloneWorkspaceMemberMutationSignalV2(input.signal) }),
  });
}

function prepareWorkspaceMemberMutationRemoveV2(
  input: DesktopWorkspaceMemberMutationRemoveInputV2,
): PreparedWorkspaceMemberMutationV2 {
  if (
    !isPlainRecordV2(input) ||
    !hasExactOptionalKeysV2(input, REMOVE_INPUT_KEYS_V2) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'workspaceId') ||
    !Object.hasOwn(input, 'userId')
  ) {
    throw workspaceMemberMutationInputInvalidV2();
  }
  const config = cloneWorkspaceMemberMutationRuntimeConfigV2(input.config);
  return Object.freeze({
    kind: 'remove',
    config,
    workspaceId: cloneWorkspaceMemberMutationWorkspaceIdV2(config, input.workspaceId),
    userId: cloneWorkspaceMemberMutationUserIdV2(input.userId),
    ...(input.signal === undefined
      ? {}
      : { signal: cloneWorkspaceMemberMutationSignalV2(input.signal) }),
  });
}

function requirePreparedRoleV2(prepared: PreparedWorkspaceMemberMutationV2): WorkspaceMemberRole {
  if (prepared.role === undefined) throw workspaceMemberMutationInputInvalidV2();
  return prepared.role;
}

function assertExpectedWorkspaceMemberMutationInputV2(
  expected: PreparedWorkspaceMemberMutationV2,
  userId: string,
  role: WorkspaceMemberRole | undefined,
  signal: AbortSignal | undefined,
): void {
  if (userId !== expected.userId || role !== expected.role) {
    throw workspaceMemberMutationInputInvalidV2();
  }
  assertWorkspaceMemberMutationSignalV2(expected.signal, signal);
}

function assertWorkspaceMemberMutationOperationV2(
  kind: PreparedWorkspaceMemberMutationV2['kind'],
  expected: PreparedWorkspaceMemberMutationV2,
  isOperationActive: () => boolean,
): void {
  if (!isOperationActive()) {
    throw new RuntimeV2Error(
      'desktop_workspace_member_mutation_operation_released',
      'desktop workspace-member mutation operation has been released',
    );
  }
  if (expected.kind !== kind) throw workspaceMemberMutationInputInvalidV2();
}

function requireWorkspaceMemberMutationServiceV2(
  value: unknown,
): DesktopWorkspaceMemberMutationAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidWorkspaceMemberMutationServiceV2();
  }
  return value as unknown as DesktopWorkspaceMemberMutationAuthorityServiceV2;
}

function requireWorkspaceMemberMutationAuthorityV2(
  value: unknown,
): DesktopWorkspaceMemberMutationAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== AUTHORITY_KEYS_V2.size ||
    !Object.keys(value).every((key) => AUTHORITY_KEYS_V2.has(key)) ||
    typeof value.addMember !== 'function' ||
    typeof value.updateMemberRole !== 'function' ||
    typeof value.removeMember !== 'function'
  ) {
    throw invalidWorkspaceMemberMutationServiceV2();
  }
  return value as unknown as DesktopWorkspaceMemberMutationAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopWorkspaceMemberMutationAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function invalidWorkspaceMemberMutationServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_member_mutation_service_invalid',
    'desktop workspace-member mutation authority service is invalid',
  );
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) =>
      candidate.module_ref === DESKTOP_WORKSPACE_MEMBER_MUTATION_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_workspace_member_mutation_authority_catalog_missing',
      'desktop workspace-member mutation authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
