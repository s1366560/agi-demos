import {
  requireHttpExecutionV2,
  type ConversationMessagingExecutionV2,
} from './desktopConversationMessagingExecutionContractV2';
export { assertLocalMessagingExecutionV2 } from './desktopConversationMessagingExecutionContractV2';
export type { ConversationMessagingExecutionV2 } from './desktopConversationMessagingExecutionContractV2';
import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';
import type {
  AgentConversation,
  ComposerContextItem,
  DesktopRuntimeConfig,
  WorkspaceMessage,
} from '../types';
import type { DesktopRendererGenerationActionsV2 } from './desktopRendererGenerationContextV2';
import { createDesktopNewThreadCreationOperationsV2 } from './desktopNewThreadCreationAuthorityModuleV2';
import { createDesktopNewTaskFlowOperationsV2 } from './desktopNewTaskFlowAuthorityModuleV2';
import {
  isPlainRecordV2,
  assertMessageResponseV2,
  cloneMessageArgumentsV2,
  cloneRuntimeConfigV2,
} from './desktopNewTaskFlowContractV2';
import {
  assertUnboundAgentConversationV2,
  assertQueuedAgentMessageV2,
  type QueuedAgentMessageReceiptV2,
  cloneAgentConversationArgumentsV2,
  cloneAgentMessageArgumentsV2,
} from './desktopNewThreadCreationContractV2';
import {
  cloneMessagingConversationV2,
  cloneMessagingJsonV2,
  requireConversationWorkspaceBindingV2,
} from './desktopConversationWorkspaceBindingContractV2';

export const DESKTOP_CONVERSATION_MESSAGING_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/conversation-messaging-authority';
export const DESKTOP_CONVERSATION_MESSAGING_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.conversation-messaging-authority';
export const DESKTOP_CONVERSATION_MESSAGING_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopConversationMessagingClientV2 {
  assertActive(): void;
  createAgentConversation(
    title: string,
    projectId: string,
    userId: string,
  ): Promise<AgentConversation>;
  sendMessage(
    content: string,
    parentId?: string,
    context?: ComposerContextItem[],
    mentions?: string[],
  ): Promise<WorkspaceMessage>;
  bindConversationWorkspace(conversation: AgentConversation): Promise<AgentConversation>;
  runAgentMessage(
    conversation: AgentConversation,
    message: string,
    messageId: string,
    execution?: ConversationMessagingExecutionV2,
  ): Promise<QueuedAgentMessageReceiptV2>;
}
export interface DesktopConversationMessagingOperationsV2 {
  withOperation<T>(
    input: Readonly<{ config: DesktopRuntimeConfig; signal: AbortSignal }>,
    callback: (client: DesktopConversationMessagingClientV2) => T | Promise<T>,
  ): Promise<T>;
}
export interface DesktopConversationMessagingAuthorityServiceV2 {
  bindOperation(
    config: DesktopRuntimeConfig,
    actions: DesktopRendererGenerationActionsV2,
    signal: AbortSignal,
  ): DesktopConversationMessagingClientV2;
}

export function applyDesktopConversationMessagingAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'parent-bound-messaging' || Object.keys(config).length !== 1)
    throw messagingErrorV2('config_invalid');
  const service: DesktopConversationMessagingAuthorityServiceV2 = Object.freeze({
    bindOperation(
      config: DesktopRuntimeConfig,
      actions: DesktopRendererGenerationActionsV2,
      signal: AbortSignal,
    ) {
      const creation = createDesktopNewThreadCreationOperationsV2(() => actions).bindOperation(
        config,
      );
      const unboundConfig = Object.freeze({ ...config, workspaceId: '' });
      const unboundCreation = createDesktopNewThreadCreationOperationsV2(
        () => actions,
      ).bindOperation(unboundConfig);
      const taskFlow = createDesktopNewTaskFlowOperationsV2(() => actions).bindOperation(config);
      return Object.freeze({
        assertActive: () => signal.throwIfAborted(),
        createAgentConversation: (title: string, projectId: string, userId: string) =>
          unboundCreation.createAgentConversation(
            title,
            projectId,
            userId,
            undefined,
            undefined,
            signal,
          ),
        sendMessage: (
          content: string,
          parentId?: string,
          context?: ComposerContextItem[],
          mentions?: string[],
        ) => taskFlow.sendMessage(content, parentId, context, mentions, signal),
        bindConversationWorkspace: (conversation: AgentConversation) =>
          creation.bindConversationWorkspace(conversation, signal),
        runAgentMessage: (
          conversation: AgentConversation,
          message: string,
          messageId: string,
          execution?: ConversationMessagingExecutionV2,
        ) =>
          creation.runAgentMessage(
            conversation.id,
            message,
            messageId,
            config.projectId,
            undefined,
            requireHttpExecutionV2(execution),
            signal,
          ),
      });
    },
  });
  context.provide(DESKTOP_CONVERSATION_MESSAGING_AUTHORITY_SERVICE_V2, service);
}

export const desktopConversationMessagingAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_CONVERSATION_MESSAGING_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigestV2(),
  apply: applyDesktopConversationMessagingAuthorityV2,
});

export function createDesktopConversationMessagingOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopConversationMessagingOperationsV2 {
  return Object.freeze({
    async withOperation<T>(
      input: Readonly<{ config: DesktopRuntimeConfig; signal: AbortSignal }>,
      callback: (client: DesktopConversationMessagingClientV2) => T | Promise<T>,
    ): Promise<T> {
      const config = cloneRuntimeConfigV2(input.config);
      const signal = input.signal;
      if (!(signal instanceof AbortSignal) || typeof callback !== 'function')
        throw messagingErrorV2('input_invalid');
      signal.throwIfAborted();
      const actions = resolveActions();
      if (!actions) throw messagingErrorV2('generation_actions_unavailable');
      const parent =
        await actions.acquireServiceOperationLease<DesktopConversationMessagingAuthorityServiceV2>({
          service: DESKTOP_CONVERSATION_MESSAGING_AUTHORITY_SERVICE_V2,
          version: DESKTOP_CONVERSATION_MESSAGING_AUTHORITY_VERSION_V2,
          scope: { kind: 'project', tenant_id: config.tenantId, project_id: config.projectId },
        });
      if (parent.status !== 'accepted')
        throw new RuntimeV2Error(parent.reasonCode, parent.runtimeCode ?? parent.reasonCode);
      let active = true;
      let consumed = false;
      let failed = false;
      let result!: T;
      const pending = new Set<Promise<unknown>>();
      let drainFailure: unknown;
      let drainFailed = false;
      const check = () => {
        if (!active) throw messagingErrorV2('operation_released');
        signal.throwIfAborted();
      };
      try {
        signal.throwIfAborted();
        const acquireChild = parent.acquireChildServiceLease;
        if (!acquireChild) throw messagingErrorV2('parent_lease_required');
        const childActions = Object.freeze<DesktopRendererGenerationActionsV2>({
          acquireOperationLease() {
            throw messagingErrorV2('service_lease_required');
          },
          acquireServiceOperationLease(request) {
            check();
            return acquireChild(request);
          },
        });
        result = await parent.useService(async (service) => {
          check();
          if (consumed) throw messagingErrorV2('operation_released');
          consumed = true;
          if (!service || typeof service.bindOperation !== 'function')
            throw messagingErrorV2('service_invalid');
          const delegate = service.bindOperation(config, childActions, signal);
          const track = <TValue>(run: () => Promise<TValue>): Promise<TValue> => {
            check();
            const promise = run().then((value) => {
              signal.throwIfAborted();
              return value;
            });
            pending.add(promise);
            void promise.then(
              () => pending.delete(promise),
              (error) => {
                pending.delete(promise);
                void error;
              },
            );
            return promise;
          };
          const client = guardedClientV2(delegate, config, check, track);
          return await callback(client);
        });
        signal.throwIfAborted();
      } catch (error) {
        failed = true;
        throw error;
      } finally {
        active = false;
        const settled = await Promise.allSettled([...pending]);
        const rejected = settled.find((item) => item.status === 'rejected');
        if (rejected?.status === 'rejected') {
          drainFailed = true;
          drainFailure = rejected.reason;
        }
        try {
          await parent.release();
        } catch (error) {
          if (!failed && !drainFailed) throw error;
        }
      }
      signal.throwIfAborted();
      if (drainFailed) throw drainFailure;
      return result;
    },
  });
}

function guardedClientV2(
  delegate: DesktopConversationMessagingClientV2,
  config: DesktopRuntimeConfig,
  check: () => void,
  track: <T>(run: () => Promise<T>) => Promise<T>,
): DesktopConversationMessagingClientV2 {
  for (const method of [
    'createAgentConversation',
    'sendMessage',
    'bindConversationWorkspace',
    'runAgentMessage',
  ] as const) {
    if (!delegate || typeof delegate[method] !== 'function')
      throw messagingErrorV2('service_invalid');
  }
  return Object.freeze({
    assertActive: check,
    createAgentConversation(title: string, projectId: string, userId: string) {
      check();
      const unboundConfig = Object.freeze({ ...config, workspaceId: '' });
      const args = cloneAgentConversationArgumentsV2(unboundConfig, title, projectId, userId);
      return track(() =>
        delegate
          .createAgentConversation(args.title, args.projectId, args.expectedUserId)
          .then((value) => assertUnboundAgentConversationV2(value, unboundConfig, args)),
      );
    },
    sendMessage(
      content: string,
      parentId?: string,
      context?: ComposerContextItem[],
      mentions?: string[],
    ) {
      check();
      const args = cloneMessageArgumentsV2(config, content, parentId, context, mentions);
      return track(() =>
        delegate
          .sendMessage(args.content, args.parentMessageId, args.contextItems, args.mentions)
          .then((value) => assertMessageResponseV2(value, config)),
      );
    },
    bindConversationWorkspace(conversation: AgentConversation) {
      check();
      if (!config.workspaceId) throw messagingErrorV2('workspace_required');
      const expected = cloneMessagingConversationV2(conversation, config, true);
      return track(() =>
        delegate
          .bindConversationWorkspace(expected)
          .then((value) => requireConversationWorkspaceBindingV2(value, config, expected)),
      );
    },
    runAgentMessage(
      conversation: AgentConversation,
      message: string,
      messageId: string,
      execution?: ConversationMessagingExecutionV2,
    ) {
      check();
      const expected = cloneMessagingConversationV2(conversation, config);
      const frozenExecution = execution === undefined ? undefined : cloneMessagingJsonV2(execution);
      const args = cloneAgentMessageArgumentsV2(
        config,
        expected.id,
        message,
        messageId,
        config.projectId,
        undefined,
        requireHttpExecutionV2(frozenExecution),
      );
      return track(() =>
        delegate
          .runAgentMessage(expected, args.message, args.messageId as string, frozenExecution)
          .then((value) => {
            if (
              config.mode === 'local' &&
              (!isPlainRecordV2(value) ||
                value.message_id !== args.messageId ||
                typeof value.created !== 'boolean' ||
                typeof value.replayed !== 'boolean' ||
                !(
                  (value.queued === true && value.created === true && value.replayed === false) ||
                  (value.queued === false && value.created === false && value.replayed === true)
                ))
            ) {
              throw messagingErrorV2('message_receipt_invalid');
            }
            return assertQueuedAgentMessageV2(value);
          }),
      );
    },
  });
}

function messagingErrorV2(suffix: string): RuntimeV2Error {
  return new RuntimeV2Error(`desktop_conversation_messaging_${suffix}`, suffix);
}
function generatedDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_CONVERSATION_MESSAGING_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry) throw messagingErrorV2('catalog_missing');
  return entry.contract_digest;
}
