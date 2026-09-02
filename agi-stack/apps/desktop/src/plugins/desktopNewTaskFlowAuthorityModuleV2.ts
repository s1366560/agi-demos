import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
  type ScopeV2,
} from '@agistack/plugin-runtime';

import { DesktopApiClient } from '../api/client';
import type {
  AgentPlanMode,
  ApprovePlanAndStartRequest,
  ComposerContextItem,
  CreateTaskSessionRequest,
  DesktopRuntimeConfig,
} from '../types';
import {
  assertApprovalResponseV2,
  assertCapabilityV2,
  assertMessageResponseV2,
  assertPlanModeInputV2,
  assertPlanModeResponseV2,
  assertPlanTasksResponseV2,
  assertTaskSessionResponseV2,
  assertTimelineResponseV2,
  assertWorkspaceListV2,
  canonicalIdentifierV2,
  cloneApprovalRequestV2,
  cloneConversationArgumentsV2,
  cloneMessageArgumentsV2,
  cloneRuntimeConfigV2,
  cloneSignalV2,
  cloneTaskSessionRequestV2,
  invalidInputV2,
  isPlainRecordV2,
  type ConversationMessageOptionsV2,
} from './desktopNewTaskFlowContractV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_NEW_TASK_FLOW_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/new-task-flow-authority';
export const DESKTOP_NEW_TASK_FLOW_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.new-task-flow-authority';
export const DESKTOP_NEW_TASK_FLOW_AUTHORITY_VERSION_V2 = '1.0.0';

type DesktopNewTaskFlowMethodV2 =
  | 'approvePlanAndStart'
  | 'createTaskSession'
  | 'getConversationMessages'
  | 'listAgentPlanTasks'
  | 'listWorkspaces'
  | 'sendMessage'
  | 'supportsAgentPlanWorkflow'
  | 'switchPlanMode';

export type DesktopNewTaskFlowClientV2 = Readonly<
  Pick<DesktopApiClient, DesktopNewTaskFlowMethodV2>
>;

export interface DesktopNewTaskFlowAuthorityServiceV2 {
  readonly bindOperation: (config: DesktopRuntimeConfig) => DesktopNewTaskFlowClientV2;
}

export interface DesktopNewTaskFlowOperationsV2 {
  readonly bindOperation: (config: DesktopRuntimeConfig) => DesktopNewTaskFlowClientV2;
}

type ProjectOperationKindV2 =
  | 'create-task-session'
  | 'list-workspaces'
  | 'send-message'
  | 'supports-agent-plan-workflow';
type SessionOperationKindV2 =
  | 'approve-plan-and-start'
  | 'get-conversation-messages'
  | 'list-agent-plan-tasks'
  | 'switch-plan-mode';
type OperationKindV2 = ProjectOperationKindV2 | SessionOperationKindV2;

export type DesktopNewTaskFlowOperationInputV2 =
  | Readonly<{
      kind: 'list-workspaces' | 'supports-agent-plan-workflow';
      config: DesktopRuntimeConfig;
      signal?: AbortSignal;
    }>
  | Readonly<{
      kind: 'create-task-session';
      config: DesktopRuntimeConfig;
      input: CreateTaskSessionRequest;
    }>
  | Readonly<{
      kind: 'send-message';
      config: DesktopRuntimeConfig;
      content: string;
      parentMessageId?: string;
      contextItems?: ComposerContextItem[];
      mentions?: string[];
    }>
  | Readonly<{
      kind: 'get-conversation-messages';
      config: DesktopRuntimeConfig;
      conversationId: string;
      projectId?: string;
      options?: ConversationMessageOptionsV2;
    }>
  | Readonly<{
      kind: 'list-agent-plan-tasks';
      config: DesktopRuntimeConfig;
      conversationId: string;
      signal?: AbortSignal;
    }>
  | Readonly<{
      kind: 'switch-plan-mode';
      config: DesktopRuntimeConfig;
      conversationId: string;
      mode: AgentPlanMode;
    }>
  | Readonly<{
      kind: 'approve-plan-and-start';
      config: DesktopRuntimeConfig;
      input: ApprovePlanAndStartRequest;
    }>;

type PreparedOperationV2 = Readonly<{
  kind: OperationKindV2;
  config: DesktopRuntimeConfig;
  conversationId?: string;
  signal?: AbortSignal;
  input?: CreateTaskSessionRequest | ApprovePlanAndStartRequest;
  content?: string;
  parentMessageId?: string;
  contextItems?: ComposerContextItem[];
  mentions?: string[];
  projectId?: string;
  options?: ConversationMessageOptionsV2;
  mode?: AgentPlanMode;
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

const AUTHORITY_METHODS_V2 = new Set<DesktopNewTaskFlowMethodV2>([
  'approvePlanAndStart',
  'createTaskSession',
  'getConversationMessages',
  'listAgentPlanTasks',
  'listWorkspaces',
  'sendMessage',
  'supportsAgentPlanWorkflow',
  'switchPlanMode',
]);
export class DesktopNewTaskFlowAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopNewTaskFlowAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopNewTaskFlowAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_new_task_flow_authority_config_invalid',
      'desktop new-task flow authority requires desktop-api-client strategy',
    );
  }
  const service: DesktopNewTaskFlowAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopNewTaskFlowAuthorityV2,
  });
  context.provide(DESKTOP_NEW_TASK_FLOW_AUTHORITY_SERVICE_V2, service);
}

export const desktopNewTaskFlowAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_NEW_TASK_FLOW_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopNewTaskFlowAuthorityV2,
});

export function createDesktopNewTaskFlowOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopNewTaskFlowOperationsV2 {
  return Object.freeze({
    bindOperation: (config: DesktopRuntimeConfig) =>
      createGenerationBoundClientV2(resolveActions, config),
  });
}

function createGenerationBoundClientV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
  config: DesktopRuntimeConfig,
): DesktopNewTaskFlowClientV2 {
  return Object.freeze({
    async listWorkspaces(signal?: AbortSignal) {
      const prepared = prepareOperationV2({ kind: 'list-workspaces', config, signal });
      return await runOperationV2(requireGenerationActionsV2(resolveActions()), prepared, (client) =>
        client.listWorkspaces(prepared.signal),
      );
    },
    async supportsAgentPlanWorkflow(signal?: AbortSignal) {
      const prepared = prepareOperationV2({
        kind: 'supports-agent-plan-workflow',
        config,
        signal,
      });
      return await runOperationV2(requireGenerationActionsV2(resolveActions()), prepared, (client) =>
        client.supportsAgentPlanWorkflow(prepared.signal),
      );
    },
    async createTaskSession(input: CreateTaskSessionRequest) {
      const prepared = prepareOperationV2({ kind: 'create-task-session', config, input });
      return await runOperationV2(requireGenerationActionsV2(resolveActions()), prepared, (client) =>
        client.createTaskSession(prepared.input as CreateTaskSessionRequest),
      );
    },
    async sendMessage(
      content: string,
      parentMessageId?: string,
      contextItems: ComposerContextItem[] = [],
      mentions: string[] = [],
    ) {
      const prepared = prepareOperationV2({
        kind: 'send-message',
        config,
        content,
        parentMessageId,
        contextItems,
        mentions,
      });
      return await runOperationV2(requireGenerationActionsV2(resolveActions()), prepared, (client) =>
        client.sendMessage(
          prepared.content as string,
          prepared.parentMessageId,
          prepared.contextItems,
          prepared.mentions,
        ),
      );
    },
    async getConversationMessages(
      conversationId: string,
      projectId?: string,
      options: ConversationMessageOptionsV2 = {},
    ) {
      const prepared = prepareOperationV2({
        kind: 'get-conversation-messages',
        config,
        conversationId,
        projectId,
        options,
      });
      return await runOperationV2(requireGenerationActionsV2(resolveActions()), prepared, (client) =>
        client.getConversationMessages(
          prepared.conversationId as string,
          prepared.projectId,
          prepared.options,
        ),
      );
    },
    async listAgentPlanTasks(conversationId: string, signal?: AbortSignal) {
      const prepared = prepareOperationV2({
        kind: 'list-agent-plan-tasks',
        config,
        conversationId,
        signal,
      });
      return await runOperationV2(requireGenerationActionsV2(resolveActions()), prepared, (client) =>
        client.listAgentPlanTasks(prepared.conversationId as string, prepared.signal),
      );
    },
    async switchPlanMode(conversationId: string, mode: AgentPlanMode) {
      const prepared = prepareOperationV2({
        kind: 'switch-plan-mode',
        config,
        conversationId,
        mode,
      });
      return await runOperationV2(requireGenerationActionsV2(resolveActions()), prepared, (client) =>
        client.switchPlanMode(prepared.conversationId as string, prepared.mode as AgentPlanMode),
      );
    },
    async approvePlanAndStart(input: ApprovePlanAndStartRequest) {
      const prepared = prepareOperationV2({ kind: 'approve-plan-and-start', config, input });
      return await runOperationV2(requireGenerationActionsV2(resolveActions()), prepared, (client) =>
        client.approvePlanAndStart(prepared.input as ApprovePlanAndStartRequest),
      );
    },
  });
}

export function withDesktopNewTaskFlowAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopNewTaskFlowOperationInputV2,
  operation: (
    authority: DesktopNewTaskFlowClientV2,
    prepared: PreparedOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runOperationV2(actions, prepareOperationV2(input), operation);
}

async function runOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedOperationV2,
  operation: (
    authority: DesktopNewTaskFlowClientV2,
    prepared: PreparedOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopNewTaskFlowAuthorityServiceV2>({
      service: DESKTOP_NEW_TASK_FLOW_AUTHORITY_SERVICE_V2,
      version: DESKTOP_NEW_TASK_FLOW_AUTHORITY_VERSION_V2,
      scope: operationScopeV2(prepared),
    });
  if (admission.status === 'rejected') {
    throw new DesktopNewTaskFlowAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireServiceV2(candidate);
      const authority = requireAuthorityV2(service.bindOperation(prepared.config));
      return operation(
        createGuardedAuthorityV2(
          authority,
          prepared.config,
          prepared.kind,
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

function createDesktopNewTaskFlowAuthorityV2(
  config: DesktopRuntimeConfig,
): DesktopNewTaskFlowClientV2 {
  const operationConfig = cloneRuntimeConfigV2(config);
  return createGuardedAuthorityV2(
    new DesktopApiClient(operationConfig),
    operationConfig,
    null,
    () => true,
  );
}

function createGuardedAuthorityV2(
  authority: DesktopNewTaskFlowClientV2,
  config: DesktopRuntimeConfig,
  allowedKind: OperationKindV2 | null,
  isOperationActive: () => boolean,
): DesktopNewTaskFlowClientV2 {
  const requireCall = (kind: OperationKindV2) => {
    if (!isOperationActive()) {
      throw new RuntimeV2Error(
        'desktop_new_task_flow_operation_released',
        'desktop new-task flow operation has been released',
      );
    }
    if (allowedKind !== null && kind !== allowedKind) {
      throw new RuntimeV2Error(
        'desktop_new_task_flow_operation_kind_mismatch',
        'desktop new-task flow operation differs from its acquired lease',
      );
    }
  };
  return Object.freeze({
    listWorkspaces(signal?: AbortSignal) {
      requireCall('list-workspaces');
      const checkedSignal = cloneSignalV2(signal);
      return authority
        .listWorkspaces(checkedSignal)
        .then((value) => assertWorkspaceListV2(value, config));
    },
    supportsAgentPlanWorkflow(signal?: AbortSignal) {
      requireCall('supports-agent-plan-workflow');
      const checkedSignal = cloneSignalV2(signal);
      return authority.supportsAgentPlanWorkflow(checkedSignal).then(assertCapabilityV2);
    },
    createTaskSession(input: CreateTaskSessionRequest) {
      requireCall('create-task-session');
      const request = cloneTaskSessionRequestV2(input);
      return authority
        .createTaskSession(request)
        .then((value) => assertTaskSessionResponseV2(value, config));
    },
    sendMessage(
      content: string,
      parentMessageId?: string,
      contextItems: ComposerContextItem[] = [],
      mentions: string[] = [],
    ) {
      requireCall('send-message');
      const args = cloneMessageArgumentsV2(
        config,
        content,
        parentMessageId,
        contextItems,
        mentions,
      );
      return authority
        .sendMessage(args.content, args.parentMessageId, args.contextItems, args.mentions)
        .then((value) => assertMessageResponseV2(value, config));
    },
    getConversationMessages(
      conversationId: string,
      projectId?: string,
      options: ConversationMessageOptionsV2 = {},
    ) {
      requireCall('get-conversation-messages');
      const args = cloneConversationArgumentsV2(config, conversationId, projectId, options);
      return authority
        .getConversationMessages(args.conversationId, args.projectId, args.options)
        .then((value) => assertTimelineResponseV2(value, args.conversationId));
    },
    listAgentPlanTasks(conversationId: string, signal?: AbortSignal) {
      requireCall('list-agent-plan-tasks');
      const checkedConversationId = canonicalIdentifierV2(conversationId);
      const checkedSignal = cloneSignalV2(signal);
      return authority
        .listAgentPlanTasks(checkedConversationId, checkedSignal)
        .then((value) => assertPlanTasksResponseV2(value, checkedConversationId));
    },
    switchPlanMode(conversationId: string, mode: AgentPlanMode) {
      requireCall('switch-plan-mode');
      const checkedConversationId = canonicalIdentifierV2(conversationId);
      const checkedMode = assertPlanModeInputV2(mode);
      return authority
        .switchPlanMode(checkedConversationId, checkedMode)
        .then((value) => assertPlanModeResponseV2(value, checkedConversationId, checkedMode));
    },
    approvePlanAndStart(input: ApprovePlanAndStartRequest) {
      requireCall('approve-plan-and-start');
      const request = cloneApprovalRequestV2(config, input);
      return authority
        .approvePlanAndStart(request)
        .then((value) => assertApprovalResponseV2(value, request));
    },
  });
}

function prepareOperationV2(input: DesktopNewTaskFlowOperationInputV2): PreparedOperationV2 {
  if (!isPlainRecordV2(input) || typeof input.kind !== 'string') throw invalidInputV2();
  const config = cloneRuntimeConfigV2(input.config);
  switch (input.kind) {
    case 'list-workspaces':
    case 'supports-agent-plan-workflow':
      return Object.freeze({ kind: input.kind, config, signal: cloneSignalV2(input.signal) });
    case 'create-task-session':
      return Object.freeze({ kind: input.kind, config, input: cloneTaskSessionRequestV2(input.input) });
    case 'send-message': {
      const args = cloneMessageArgumentsV2(
        config,
        input.content,
        input.parentMessageId,
        input.contextItems,
        input.mentions,
      );
      return Object.freeze({ kind: input.kind, config, ...args });
    }
    case 'get-conversation-messages': {
      const args = cloneConversationArgumentsV2(
        config,
        input.conversationId,
        input.projectId,
        input.options,
      );
      return Object.freeze({ kind: input.kind, config, ...args });
    }
    case 'list-agent-plan-tasks':
      return Object.freeze({
        kind: input.kind,
        config,
        conversationId: canonicalIdentifierV2(input.conversationId),
        signal: cloneSignalV2(input.signal),
      });
    case 'switch-plan-mode': {
      const mode = assertPlanModeInputV2(input.mode);
      return Object.freeze({
        kind: input.kind,
        config,
        conversationId: canonicalIdentifierV2(input.conversationId),
        mode,
      });
    }
    case 'approve-plan-and-start': {
      const request = cloneApprovalRequestV2(config, input.input);
      return Object.freeze({
        kind: input.kind,
        config,
        conversationId: request.conversationId,
        input: request,
      });
    }
    default:
      throw invalidInputV2();
  }
}

function operationScopeV2(prepared: PreparedOperationV2): ScopeV2 {
  if (
    prepared.kind === 'create-task-session' ||
    prepared.kind === 'list-workspaces' ||
    prepared.kind === 'send-message' ||
    prepared.kind === 'supports-agent-plan-workflow'
  ) {
    return Object.freeze({
      kind: 'project',
      tenant_id: prepared.config.tenantId,
      project_id: prepared.config.projectId,
    });
  }
  return Object.freeze({
    kind: 'session',
    tenant_id: prepared.config.tenantId,
    project_id: prepared.config.projectId,
    session_id: prepared.conversationId as string,
  });
}

function requireServiceV2(value: unknown): DesktopNewTaskFlowAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).some((key) => key !== 'bindOperation') ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopNewTaskFlowAuthorityServiceV2;
}

function requireAuthorityV2(value: unknown): DesktopNewTaskFlowClientV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).some((key) => !AUTHORITY_METHODS_V2.has(key as DesktopNewTaskFlowMethodV2)) ||
    [...AUTHORITY_METHODS_V2].some((method) => typeof value[method] !== 'function')
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopNewTaskFlowClientV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null && typeof actions.acquireServiceOperationLease === 'function') return actions;
  throw new DesktopNewTaskFlowAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_new_task_flow_service_invalid',
    'desktop new-task flow authority service is invalid',
  );
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === DESKTOP_NEW_TASK_FLOW_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_new_task_flow_authority_catalog_missing',
      'desktop new-task flow authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
