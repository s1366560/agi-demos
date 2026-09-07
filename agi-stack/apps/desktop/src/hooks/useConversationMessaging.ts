import { assertLocalMessagingExecutionV2 } from '../plugins/desktopConversationMessagingExecutionContractV2';
import { useConversationMessagingLifetime } from './useConversationMessagingLifetime';
import { useI18n } from '../i18n';
import {
  composerAgentExecutionContext,
  workspaceMessageRequiresDefaultAgentLaunch,
} from '../features/chat/chatComposerModel';
import { permissionModeForPreset } from '../features/chat/permissionPresetModel';
import { resolveSessionComposerDispatch } from '../features/session/sessionComposerDispatchModel';
import {
  AgentConversation,
  CodeRangeReference,
  ComposerContextItem,
  DesktopRunInput,
  RunInputDelivery,
} from '../types';
import { formatConnectionError } from '../utils/format';
import {
  mergeTimelineItems,
  optimisticUserTimelineItem,
  timelineCursorFromFirst,
  timelineCursorFromLast,
} from '../features/chat/appTimelineEventModel';
import { agentConversationScopeKey } from '../appShellTypes';
import type { AgentConversationParams } from './useAgentConversation';

export function useConversationMessaging(params: AgentConversationParams) {
  const { t } = useI18n();
  const {
    sessionProjection,
    permissionPreset,
    runInputReferences,
    runInputDelivery,
    runInputDeliveryOptions,
    sessionChatDisabledReason,
    localRuntimeMode,
    messagingOperationsV2,
    sessionRunInputOperationsV2,
    socket,
    runInputRequestRef,
  } = params;
  const beginRequest = useConversationMessagingLifetime(params);
  const sendMessageContent = async (
    rawContent: string,
    contextItems: ComposerContextItem[],
    onWorkspaceMessageSaved?: () => void,
    referencesOverride?: CodeRangeReference[],
  ) => {
    const request = beginRequest();
    if (!request) return;
    const { assertActive, signal, adoptConversation } = request;
    const requestParams = request.guardParams(params);
    const {
      setDataset,
      setError,
      setSending,
      setRunInputReferences,
      setRunInputs,
      setAgentConversationSession,
      setConversationTimeline,
      invalidateSessionAuthority,
      upsertAgentTaskSignal,
      loadConversationTimeline,
    } = requestParams;
    const config = Object.freeze({ ...params.config });
    const userId = params.auth.user?.user_id ?? '';
    const selectedConversation =
      params.selectedConversation && structuredClone(params.selectedConversation);
    const currentArtifactRun =
      params.currentArtifactRun && structuredClone(params.currentArtifactRun);
    const agentConversationSession =
      params.agentConversationSession && structuredClone(params.agentConversationSession);
    const workspace = params.dataset.workspaces.find(
      (item) => item.id === config.workspaceId.trim(),
    );
    const workspaceLabel = workspace?.name || workspace?.title || 'Desktop workspace';

    contextItems = structuredClone(contextItems);
    referencesOverride = referencesOverride && structuredClone(referencesOverride);
    const content = rawContent.trim();
    if (!content) return;
    // Review-panel comment sends carry their own deduplicated anchors; the
    // composer's selected references otherwise stay the default.
    const outgoingReferences = structuredClone(referencesOverride ?? runInputReferences);
    const execution = composerAgentExecutionContext(content, contextItems);
    const mentions = execution.mentions;
    const canSendConversationMessage = Boolean(
      sessionProjection?.capabilities.canSendMessage &&
      sessionProjection.capabilities.allowedActions.includes('send_message'),
    );
    const canSendRunInput = Boolean(
      runInputDeliveryOptions.length > 0 &&
      currentArtifactRun &&
      selectedConversation?.id === currentArtifactRun.conversation_id &&
      (currentArtifactRun.status === 'queued' || currentArtifactRun.status === 'running'),
    );
    const composerDispatch = resolveSessionComposerDispatch({
      requestedDelivery: runInputDelivery,
      availableDeliveries: runInputDeliveryOptions,
      hasActiveRun: Boolean(
        currentArtifactRun &&
        (currentArtifactRun.status === 'queued' || currentArtifactRun.status === 'running'),
      ),
      canSendConversationMessage,
      canSendRunInput,
    });
    if (selectedConversation && composerDispatch.kind === 'blocked') {
      setError(t('session.authorityActionUnavailable'));
      return;
    }
    if (sessionChatDisabledReason) {
      setError(sessionChatDisabledReason);
      return;
    }
    request.start();
    setSending(true);
    setError(null);
    const signalId = `agent-task-${Date.now()}`;
    upsertAgentTaskSignal({
      id: signalId,
      content,
      status: 'saving',
      detail: config.workspaceId.trim()
        ? 'Saving workspace message before handing it to the Agent.'
        : 'Opening the Agent conversation.',
      createdAt: new Date().toISOString(),
    });
    try {
      if (composerDispatch.kind === 'run_input' && currentArtifactRun) {
        const requestedDelivery = composerDispatch.delivery;
        const signature = JSON.stringify({
          runId: currentArtifactRun.id,
          revision: currentArtifactRun.revision,
          delivery: requestedDelivery,
          content,
          references: outgoingReferences,
          contextItems,
        });
        if (runInputRequestRef.current?.signature !== signature) {
          const requestId =
            globalThis.crypto?.randomUUID?.() ??
            `${Date.now()}-${Math.random().toString(36).slice(2)}`;
          runInputRequestRef.current = {
            signature,
            messageId: `desktop-run-input-${requestId}`,
            idempotencyKey: `desktop-run-input:${currentArtifactRun.id}:${requestId}`,
          };
        }
        const request = runInputRequestRef.current;
        const requestConfig = config;
        if (!selectedConversation) {
          throw new Error('session_run_input_conversation_unavailable');
        }
        const acknowledgement = await sessionRunInputOperationsV2.createRunInput({
          config: requestConfig,
          signal,
          conversation: selectedConversation,
          runId: currentArtifactRun.id,
          request: {
            expectedRunRevision: currentArtifactRun.revision,
            message: content,
            messageId: request.messageId,
            idempotencyKey: request.idempotencyKey,
            delivery: requestedDelivery,
            references: outgoingReferences,
            contextItems,
          },
        });
        assertActive();
        const acknowledgementInput: DesktopRunInput = acknowledgement.input;
        const acknowledgementConversationId = acknowledgement.conversation_id;
        const acknowledgementMessageId = acknowledgement.message_id;
        const acknowledgementDeliveryMode: RunInputDelivery = acknowledgement.delivery_mode;
        const acknowledgementQueuePosition = acknowledgement.queue_position;
        assertActive();
        onWorkspaceMessageSaved?.();
        if (!referencesOverride) setRunInputReferences([]);
        setRunInputs((current) =>
          [
            ...current.filter((input) => input.id !== acknowledgementInput.id),
            acknowledgementInput,
          ].sort((left, right) => left.sequence - right.sequence),
        );
        assertActive();
        if (runInputRequestRef.current === request) runInputRequestRef.current = null;
        upsertAgentTaskSignal({
          id: signalId,
          conversationId: acknowledgementConversationId,
          messageId: acknowledgementMessageId,
          status: 'acknowledged',
          detail:
            acknowledgementDeliveryMode === 'steer_now'
              ? t('session.steeringAccepted')
              : t('session.queueAccepted', {
                  position: acknowledgementQueuePosition ?? '—',
                }),
        });
        invalidateSessionAuthority();
        if (selectedConversation) {
          await loadConversationTimeline(
            selectedConversation,
            requestConfig.projectId,
            requestConfig,
          );
        }
        return;
      }
      await messagingOperationsV2.withOperation({ config, signal }, async (client) => {
        const assertOperationActive = () => {
          assertActive();
          client.assertActive();
        };
        assertOperationActive();
        const ensureAgentConversation = async (
          firstMessage: string,
        ): Promise<AgentConversation> => {
          const scopeKey = agentConversationScopeKey(config);
          if (
            agentConversationSession?.scopeKey === scopeKey &&
            agentConversationSession.conversation.project_id === config.projectId.trim()
          ) {
            request.assertCachedSessionCurrent();
            const cached = agentConversationSession.conversation;
            if (
              cached.tenant_id !== config.tenantId.trim() ||
              (cached.workspace_id ?? null) !== (config.workspaceId.trim() || null) ||
              (config.mode === 'cloud' && cached.user_id !== userId)
            ) {
              throw new Error('conversation_messaging_cached_scope_mismatch');
            }
            return cached;
          }

          const titleSource =
            firstMessage.length > 42 ? `${firstMessage.slice(0, 39)}...` : firstMessage;
          const created = await client.createAgentConversation(
            `${workspaceLabel}: ${titleSource}`,
            config.projectId,
            userId,
          );
          assertOperationActive();
          const conversation = config.workspaceId.trim()
            ? await client.bindConversationWorkspace(created)
            : created;
          assertOperationActive();
          adoptConversation(conversation.id);
          setAgentConversationSession({ scopeKey, conversation });
          const conversationGroupKey = config.workspaceId.trim();
          setDataset((current) => ({
            ...current,
            conversationsByWorkspace: {
              ...current.conversationsByWorkspace,
              [conversationGroupKey]: [
                conversation,
                ...(current.conversationsByWorkspace[conversationGroupKey] ?? []).filter(
                  (item) => item.id !== conversation.id,
                ),
              ],
            },
          }));
          await loadConversationTimeline(conversation, config.projectId, config);
          assertOperationActive();
          return conversation;
        };

        const dispatchAgentConversationMessage = async (
          conversation: AgentConversation,
          content: string,
          execution: ReturnType<typeof composerAgentExecutionContext>,
          messageId: string,
          signalId: string,
          workspaceMessageSaved = false,
        ) => {
          assertOperationActive();
          upsertAgentTaskSignal({
            id: signalId,
            conversationId: conversation.id,
            messageId,
            status: 'queued',
            detail: 'Agent conversation opened. Sending task over WebSocket.',
          });
          assertOperationActive();
          assertLocalMessagingExecutionV2(config, { ...execution, permissionPreset });
          const queued = socket.sendAgentMessage({
            conversationId: conversation.id,
            projectId: config.projectId,
            message: execution.message,
            messageId,
            agentId: execution.agentId,
            forcedSkillName: execution.forcedSkillName,
            subAgentId: execution.subAgentId,
            mentions: execution.mentions,
            fileMetadata: execution.fileMetadata,
            appModelContext: execution.appModelContext,
            permissionMode: permissionModeForPreset(permissionPreset),
          });
          setConversationTimeline((current) => {
            if (current.conversationId !== conversation.id) return current;
            const items = mergeTimelineItems(current.items, [
              optimisticUserTimelineItem(
                messageId,
                content,
                execution.forcedSkillName,
                execution.fileMetadata,
              ),
            ]);
            return {
              ...current,
              items,
              firstCursor: timelineCursorFromFirst(items),
              lastCursor: timelineCursorFromLast(items),
            };
          });
          if (!queued && localRuntimeMode) {
            await client.runAgentMessage(conversation, execution.message, messageId, {
              ...execution,
              permissionPreset,
            });
            assertOperationActive();
            invalidateSessionAuthority();
            upsertAgentTaskSignal({
              id: signalId,
              status: 'queued',
              detail: 'Task sent to local Agent runtime over loopback HTTP.',
            });
            return;
          }
          if (!queued) {
            const websocketMessage = workspaceMessageSaved
              ? 'Message saved, but the Agent WebSocket is not connected yet.'
              : 'Message was not sent because the Agent WebSocket is disconnected.';
            setError(websocketMessage);
            upsertAgentTaskSignal({
              id: signalId,
              status: 'failed',
              detail: websocketMessage,
            });
            return;
          }
          upsertAgentTaskSignal({
            id: signalId,
            status: 'queued',
            detail: 'Task sent to Agent. Waiting for acknowledgement.',
          });
        };

        if (!config.workspaceId.trim()) {
          const conversation = await ensureAgentConversation(content);
          const messageId = `desktop-${crypto.randomUUID()}`;
          await dispatchAgentConversationMessage(
            conversation,
            content,
            execution,
            messageId,
            signalId,
          );
          assertOperationActive();
          onWorkspaceMessageSaved?.();
          return;
        }
        const saved = await client.sendMessage(content, undefined, contextItems, mentions);
        assertOperationActive();
        setDataset((current) => ({
          ...current,
          messages: [...current.messages, saved],
        }));
        assertOperationActive();
        onWorkspaceMessageSaved?.();
        upsertAgentTaskSignal({
          id: signalId,
          messageId: saved.id,
          status: 'queued',
          detail: 'Workspace message saved. Opening the Agent conversation.',
        });

        if (!workspaceMessageRequiresDefaultAgentLaunch(saved)) {
          upsertAgentTaskSignal({
            id: signalId,
            messageId: saved.id,
            status: 'acknowledged',
            detail: t('chat.workspaceMentionsRouted', {
              count: saved.mentions?.length ?? 0,
            }),
          });
        } else if (config.projectId.trim()) {
          try {
            const conversation = await ensureAgentConversation(content);
            const messageId = saved.id || `desktop-${Date.now()}`;
            await dispatchAgentConversationMessage(
              conversation,
              content,
              execution,
              messageId,
              signalId,
              true,
            );
          } catch (agentError) {
            assertOperationActive();
            const detail = `Message saved, but Agent launch failed: ${formatConnectionError(
              agentError,
              config.apiBaseUrl,
            )}`;
            setError(detail);
            upsertAgentTaskSignal({
              id: signalId,
              status: 'failed',
              detail,
            });
          }
        } else {
          upsertAgentTaskSignal({
            id: signalId,
            status: 'failed',
            detail: 'Message saved, but no project is selected for Agent launch.',
          });
        }
      });
    } catch (caught) {
      if (!request.isActive()) return;
      const detail = formatConnectionError(caught, config.apiBaseUrl);
      setError(detail);
      upsertAgentTaskSignal({
        id: signalId,
        status: 'failed',
        detail,
      });
    } finally {
      request.finish();
    }
  };
  return {
    sendMessageContent,
  };
}
