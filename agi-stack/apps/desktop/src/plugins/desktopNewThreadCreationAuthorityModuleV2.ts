import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
  type ScopeV2,
} from '@agistack/plugin-runtime';

import { DesktopApiClient } from '../api/client';
import type {
  AgentCapabilityMode,
  CreateTaskSessionRequest,
  DesktopRuntimeConfig,
  LlmRoutingRole,
} from '../types';
import {
  assertNewThreadTaskSessionResponseV2,
  assertQueuedAgentMessageV2,
  assertUnboundAgentConversationV2,
  cloneAgentConversationArgumentsV2,
  cloneAgentMessageArgumentsV2,
  cloneNewThreadRuntimeConfigV2,
  cloneTaskSessionArgumentsV2,
  isNewThreadPlainRecordV2,
  newThreadInputInvalidV2,
  type ClonedAgentConversationArgumentsV2,
  type ClonedAgentMessageArgumentsV2,
  type NewThreadAgentConfigV2,
  type NewThreadAgentExecutionV2,
} from './desktopNewThreadCreationContractV2';
import {
  DESKTOP_NEW_TASK_FLOW_AUTHORITY_SERVICE_V2,
  DESKTOP_NEW_TASK_FLOW_AUTHORITY_VERSION_V2,
  type DesktopNewTaskFlowAuthorityServiceV2,
  type DesktopNewTaskFlowClientV2,
} from './desktopNewTaskFlowAuthorityModuleV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_NEW_THREAD_CREATION_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/new-thread-creation-authority';
export const DESKTOP_NEW_THREAD_CREATION_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.new-thread-creation-authority';
export const DESKTOP_NEW_THREAD_CREATION_AUTHORITY_VERSION_V2 = '1.0.0';

type DesktopNewThreadCreationMethodV2 =
  | 'createAgentConversation'
  | 'createTaskSession'
  | 'runAgentMessage';

export type DesktopNewThreadCreationClientV2 = Readonly<
  Pick<DesktopApiClient, DesktopNewThreadCreationMethodV2>
>;

export interface DesktopNewThreadCreationAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
  ) => DesktopNewThreadCreationClientV2;
}

export interface DesktopNewThreadCreationOperationsV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
  ) => DesktopNewThreadCreationClientV2;
}

type OperationKindV2 =
  | 'create-agent-conversation'
  | 'create-task-session'
  | 'run-agent-message';

export type DesktopNewThreadCreationOperationInputV2 =
  | Readonly<{
      kind: 'create-agent-conversation';
      config: DesktopRuntimeConfig;
      title: string;
      projectId: string;
      expectedUserId: string;
      capabilityMode?: AgentCapabilityMode;
      agentConfig?: NewThreadAgentConfigV2;
    }>
  | Readonly<{
      kind: 'create-task-session';
      config: DesktopRuntimeConfig;
      input: CreateTaskSessionRequest;
    }>
  | Readonly<{
      kind: 'run-agent-message';
      config: DesktopRuntimeConfig;
      conversationId: string;
      message: string;
      messageId?: string;
      projectId?: string;
      workloadRole?: LlmRoutingRole;
      execution?: NewThreadAgentExecutionV2;
    }>;

type PreparedOperationV2 = Readonly<{
  kind: OperationKindV2;
  config: DesktopRuntimeConfig;
  conversation?: ClonedAgentConversationArgumentsV2;
  taskSession?: CreateTaskSessionRequest;
  agentMessage?: ClonedAgentMessageArgumentsV2;
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

const AUTHORITY_METHODS_V2 = new Set<DesktopNewThreadCreationMethodV2>([
  'createAgentConversation',
  'createTaskSession',
  'runAgentMessage',
]);

export class DesktopNewThreadCreationAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopNewThreadCreationAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopNewThreadCreationAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_new_thread_creation_authority_config_invalid',
      'desktop new-thread creation authority requires desktop-api-client strategy',
    );
  }
  const taskFlow = requireTaskFlowServiceV2(
    context.require<DesktopNewTaskFlowAuthorityServiceV2>(
      'task_flow',
      DESKTOP_NEW_TASK_FLOW_AUTHORITY_VERSION_V2,
    ),
  );
  const service: DesktopNewThreadCreationAuthorityServiceV2 = Object.freeze({
    bindOperation: (operationConfig: DesktopRuntimeConfig) =>
      createDesktopNewThreadCreationAuthorityV2(operationConfig, taskFlow),
  });
  context.provide(DESKTOP_NEW_THREAD_CREATION_AUTHORITY_SERVICE_V2, service);
}

export const desktopNewThreadCreationAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_NEW_THREAD_CREATION_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedContractDigestV2(),
    apply: applyDesktopNewThreadCreationAuthorityV2,
  });

export function createDesktopNewThreadCreationOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopNewThreadCreationOperationsV2 {
  return Object.freeze({
    bindOperation: (config: DesktopRuntimeConfig) =>
      createGenerationBoundClientV2(resolveActions, config),
  });
}

function createGenerationBoundClientV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
  config: DesktopRuntimeConfig,
): DesktopNewThreadCreationClientV2 {
  return Object.freeze({
    async createAgentConversation(
      title: string,
      projectId: string,
      expectedUserId: string,
      capabilityMode?: AgentCapabilityMode,
      agentConfig?: NewThreadAgentConfigV2,
    ) {
      const prepared = prepareOperationV2({
        kind: 'create-agent-conversation',
        config,
        title,
        projectId,
        expectedUserId,
        capabilityMode,
        agentConfig,
      });
      return await runOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (client) => {
          const input =
            prepared.conversation as ClonedAgentConversationArgumentsV2;
          return client.createAgentConversation(
            input.title,
            input.projectId,
            input.expectedUserId,
            input.capabilityMode,
            input.agentConfig,
          );
        },
      );
    },
    async createTaskSession(input: CreateTaskSessionRequest) {
      const prepared = prepareOperationV2({
        kind: 'create-task-session',
        config,
        input,
      });
      return await runOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (client) =>
          client.createTaskSession(
            prepared.taskSession as CreateTaskSessionRequest,
          ),
      );
    },
    async runAgentMessage(
      conversationId: string,
      message: string,
      messageId?: string,
      projectId?: string,
      workloadRole?: LlmRoutingRole,
      execution?: NewThreadAgentExecutionV2,
    ) {
      const prepared = prepareOperationV2({
        kind: 'run-agent-message',
        config,
        conversationId,
        message,
        messageId,
        projectId,
        workloadRole,
        execution,
      });
      return await runOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (client) => {
          const input = prepared.agentMessage as ClonedAgentMessageArgumentsV2;
          return client.runAgentMessage(
            input.conversationId,
            input.message,
            input.messageId,
            input.projectId,
            input.workloadRole,
            input.execution,
          );
        },
      );
    },
  });
}

export function withDesktopNewThreadCreationAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopNewThreadCreationOperationInputV2,
  operation: (
    authority: DesktopNewThreadCreationClientV2,
    prepared: PreparedOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runOperationV2(actions, prepareOperationV2(input), operation);
}

async function runOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedOperationV2,
  operation: (
    authority: DesktopNewThreadCreationClientV2,
    prepared: PreparedOperationV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopNewThreadCreationAuthorityServiceV2>(
      {
        service: DESKTOP_NEW_THREAD_CREATION_AUTHORITY_SERVICE_V2,
        version: DESKTOP_NEW_THREAD_CREATION_AUTHORITY_VERSION_V2,
        scope: operationScopeV2(prepared),
      },
    );
  if (admission.status === 'rejected') {
    throw new DesktopNewThreadCreationAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireServiceV2(candidate);
      const authority = requireAuthorityV2(
        service.bindOperation(prepared.config),
      );
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

function createDesktopNewThreadCreationAuthorityV2(
  config: DesktopRuntimeConfig,
  taskFlowService: DesktopNewTaskFlowAuthorityServiceV2,
): DesktopNewThreadCreationClientV2 {
  const operationConfig = cloneNewThreadRuntimeConfigV2(config);
  const transport = new DesktopApiClient(operationConfig);
  const taskFlow = requireTaskFlowAuthorityV2(
    taskFlowService.bindOperation(operationConfig),
  );
  return createGuardedAuthorityV2(
    Object.freeze({
      createAgentConversation:
        transport.createAgentConversation.bind(transport),
      createTaskSession: taskFlow.createTaskSession.bind(taskFlow),
      runAgentMessage: transport.runAgentMessage.bind(transport),
    }),
    operationConfig,
    null,
    () => true,
  );
}

function createGuardedAuthorityV2(
  authority: DesktopNewThreadCreationClientV2,
  config: DesktopRuntimeConfig,
  allowedKind: OperationKindV2 | null,
  isOperationActive: () => boolean,
): DesktopNewThreadCreationClientV2 {
  const requireCall = (kind: OperationKindV2) => {
    if (!isOperationActive()) {
      throw new RuntimeV2Error(
        'desktop_new_thread_creation_operation_released',
        'desktop new-thread creation operation has been released',
      );
    }
    if (allowedKind !== null && kind !== allowedKind) {
      throw new RuntimeV2Error(
        'desktop_new_thread_creation_operation_kind_mismatch',
        'desktop new-thread creation operation differs from its acquired lease',
      );
    }
  };
  return Object.freeze({
    createAgentConversation(
      title: string,
      projectId: string,
      expectedUserId: string,
      capabilityMode?: AgentCapabilityMode,
      agentConfig?: NewThreadAgentConfigV2,
    ) {
      requireCall('create-agent-conversation');
      const input = cloneAgentConversationArgumentsV2(
        config,
        title,
        projectId,
        expectedUserId,
        capabilityMode,
        agentConfig,
      );
      return authority
        .createAgentConversation(
          input.title,
          input.projectId,
          input.expectedUserId,
          input.capabilityMode,
          input.agentConfig,
        )
        .then((value) =>
          assertUnboundAgentConversationV2(value, config, input),
        );
    },
    createTaskSession(input: CreateTaskSessionRequest) {
      requireCall('create-task-session');
      const request = cloneTaskSessionArgumentsV2(config, input);
      return authority
        .createTaskSession(request)
        .then((value) =>
          assertNewThreadTaskSessionResponseV2(value, config, request),
        );
    },
    runAgentMessage(
      conversationId: string,
      message: string,
      messageId?: string,
      projectId?: string,
      workloadRole?: LlmRoutingRole,
      execution?: NewThreadAgentExecutionV2,
    ) {
      requireCall('run-agent-message');
      const input = cloneAgentMessageArgumentsV2(
        config,
        conversationId,
        message,
        messageId,
        projectId,
        workloadRole,
        execution,
      );
      return authority
        .runAgentMessage(
          input.conversationId,
          input.message,
          input.messageId,
          input.projectId,
          input.workloadRole,
          input.execution,
        )
        .then(assertQueuedAgentMessageV2);
    },
  });
}

function prepareOperationV2(
  input: DesktopNewThreadCreationOperationInputV2,
): PreparedOperationV2 {
  if (!isNewThreadPlainRecordV2(input) || typeof input.kind !== 'string') {
    throw newThreadInputInvalidV2();
  }
  const config = cloneNewThreadRuntimeConfigV2(input.config);
  switch (input.kind) {
    case 'create-agent-conversation':
      return Object.freeze({
        kind: input.kind,
        config,
        conversation: cloneAgentConversationArgumentsV2(
          config,
          input.title,
          input.projectId,
          input.expectedUserId,
          input.capabilityMode,
          input.agentConfig,
        ),
      });
    case 'create-task-session':
      return Object.freeze({
        kind: input.kind,
        config,
        taskSession: cloneTaskSessionArgumentsV2(config, input.input),
      });
    case 'run-agent-message':
      return Object.freeze({
        kind: input.kind,
        config,
        agentMessage: cloneAgentMessageArgumentsV2(
          config,
          input.conversationId,
          input.message,
          input.messageId,
          input.projectId,
          input.workloadRole,
          input.execution,
        ),
      });
    default:
      throw newThreadInputInvalidV2();
  }
}

function operationScopeV2(prepared: PreparedOperationV2): ScopeV2 {
  if (prepared.kind !== 'run-agent-message') {
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
    session_id: (prepared.agentMessage as ClonedAgentMessageArgumentsV2)
      .conversationId,
  });
}

function requireServiceV2(
  value: unknown,
): DesktopNewThreadCreationAuthorityServiceV2 {
  if (
    !isNewThreadPlainRecordV2(value) ||
    Object.keys(value).some((key) => key !== 'bindOperation') ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopNewThreadCreationAuthorityServiceV2;
}

function requireAuthorityV2(value: unknown): DesktopNewThreadCreationClientV2 {
  if (
    !isNewThreadPlainRecordV2(value) ||
    Object.keys(value).some(
      (key) =>
        !AUTHORITY_METHODS_V2.has(key as DesktopNewThreadCreationMethodV2),
    ) ||
    [...AUTHORITY_METHODS_V2].some(
      (method) => typeof value[method] !== 'function',
    )
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopNewThreadCreationClientV2;
}

function requireTaskFlowServiceV2(
  value: unknown,
): DesktopNewTaskFlowAuthorityServiceV2 {
  if (
    !isNewThreadPlainRecordV2(value) ||
    Object.keys(value).some((key) => key !== 'bindOperation') ||
    typeof value.bindOperation !== 'function'
  ) {
    throw new RuntimeV2Error(
      'desktop_new_thread_creation_task_flow_service_invalid',
      'desktop new-thread creation requires the declared task-flow service',
    );
  }
  return value as unknown as DesktopNewTaskFlowAuthorityServiceV2;
}

function requireTaskFlowAuthorityV2(
  value: unknown,
): Pick<DesktopNewTaskFlowClientV2, 'createTaskSession'> {
  if (
    !isNewThreadPlainRecordV2(value) ||
    typeof value.createTaskSession !== 'function'
  ) {
    throw new RuntimeV2Error(
      'desktop_new_thread_creation_task_flow_authority_invalid',
      'desktop new-thread creation task-flow authority is invalid',
    );
  }
  return value as Pick<DesktopNewTaskFlowClientV2, 'createTaskSession'>;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (
    actions !== null &&
    typeof actions.acquireServiceOperationLease === 'function'
  )
    return actions;
  throw new DesktopNewThreadCreationAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_new_thread_creation_service_invalid',
    'desktop new-thread creation authority service is invalid',
  );
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) =>
      candidate.module_ref ===
      DESKTOP_NEW_THREAD_CREATION_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_new_thread_creation_authority_catalog_missing',
      'desktop new-thread creation authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
