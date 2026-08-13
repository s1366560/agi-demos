import { useI18n } from '../i18n';
import {
  desktopRunInputFromCloud,
} from '../features/agent-authority/agentAuthorityProjection';
import {
  composerAgentExecutionContext,
  workspaceMessageRequiresDefaultAgentLaunch,
} from '../features/chat/chatComposerModel';
import {
  permissionModeForPreset,
} from '../features/chat/permissionPresetModel';
import {
  resolveSessionComposerDispatch,
} from '../features/session/sessionComposerDispatchModel';
import {
  AgentConversation,
  CodeRangeReference,
  ComposerContextItem,
  DesktopRunInput,
  RunInputDelivery,
} from '../types';
import {
  formatConnectionError,
} from '../utils/format';
import {
  mergeTimelineItems,
  optimisticUserTimelineItem,
  timelineCursorFromFirst,
  timelineCursorFromLast,
} from '../features/chat/appTimelineEventModel';
import {
  agentConversationScopeKey,
} from '../appShellTypes';
import type { AgentConversationParams } from './useAgentConversation';

export function useConversationMessaging(params: AgentConversationParams) {
  const { t } = useI18n();
  const {
    config,
    auth,
    dataset,
    agentConversationSession,
    selectedConversation,
    currentArtifactRun,
    sessionProjection,
    permissionPreset,
    runInputReferences,
    runInputDelivery,
    runInputDeliveryOptions,
    sessionChatDisabledReason,
    localRuntimeMode,
    api,
    socket,
    activityAuthorityAdapter,
    activityAuthorityScope,
    setDataset,
    setError,
    setSending,
    setRunInputReferences,
    setRunInputs,
    setAgentConversationSession,
    setConversationTimeline,
    runInputRequestRef,
    invalidateSessionAuthority,
    upsertAgentTaskSignal,
    loadConversationTimeline,
  } = params;
  const ensureAgentConversation = async (
    firstMessage: string,
  ): Promise<AgentConversation> => {
    const scopeKey = agentConversationScopeKey(config);
    if (
      agentConversationSession?.scopeKey === scopeKey &&
      agentConversationSession.conversation.project_id ===
        config.projectId.trim()
    ) {
      return agentConversationSession.conversation;
    }

    const workspace = dataset.workspaces.find(
      (item) => item.id === config.workspaceId.trim(),
    );
    const workspaceLabel =
      workspace?.name || workspace?.title || 'Desktop workspace';
    const titleSource =
      firstMessage.length > 42
        ? `${firstMessage.slice(0, 39)}...`
        : firstMessage;
    const created = await api.createAgentConversation(
      `${workspaceLabel}: ${titleSource}`,
      config.projectId,
      auth.user?.user_id ?? '',
    );
    const conversation = config.workspaceId.trim()
      ? await api.updateAgentConversationMode(
          created.id,
          {
            workspace_id: config.workspaceId.trim(),
          },
          config.projectId,
        )
      : created;
    setAgentConversationSession({ scopeKey, conversation });
    const conversationGroupKey = config.workspaceId.trim();
    setDataset((current) => ({
      ...current,
      conversationsByWorkspace: {
        ...current.conversationsByWorkspace,
        [conversationGroupKey]: [
          conversation,
          ...(
            current.conversationsByWorkspace[conversationGroupKey] ?? []
          ).filter((item) => item.id !== conversation.id),
        ],
      },
    }));
    void loadConversationTimeline(conversation, config.projectId);
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
    upsertAgentTaskSignal({
      id: signalId,
      conversationId: conversation.id,
      messageId,
      status: 'queued',
      detail: 'Agent conversation opened. Sending task over WebSocket.',
    });
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
      await api.runAgentMessage(
        conversation.id,
        execution.message,
        messageId,
        config.projectId,
        undefined,
        execution,
      );
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

  const sendMessageContent = async (
    rawContent: string,
    contextItems: ComposerContextItem[],
    onWorkspaceMessageSaved?: () => void,
    referencesOverride?: CodeRangeReference[],
  ) => {
    const content = rawContent.trim();
    if (!content) return;
    // Review-panel comment sends carry their own deduplicated anchors; the
    // composer's selected references otherwise stay the default.
    const outgoingReferences = referencesOverride ?? runInputReferences;
    const execution = composerAgentExecutionContext(content, contextItems);
    const mentions = execution.mentions;
    const canSendConversationMessage = Boolean(
      sessionProjection?.capabilities.canSendMessage &&
      sessionProjection.capabilities.allowedActions.includes('send_message'),
    );
    const canSendRunInput = Boolean(
      (localRuntimeMode ||
        (config.mode === 'cloud' &&
          activityAuthorityAdapter.client !== null &&
          activityAuthorityAdapter.allowedActions.includes(
            'create_run_input',
          ) &&
          activityAuthorityScope !== undefined)) &&
      currentArtifactRun &&
      selectedConversation?.id === currentArtifactRun.conversation_id &&
      (currentArtifactRun.status === 'queued' ||
        currentArtifactRun.status === 'running'),
    );
    const composerDispatch = resolveSessionComposerDispatch({
      requestedDelivery: runInputDelivery,
      availableDeliveries: runInputDeliveryOptions,
      hasActiveRun: Boolean(
        currentArtifactRun &&
          (currentArtifactRun.status === 'queued' ||
            currentArtifactRun.status === 'running'),
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
        let acknowledgementInput: DesktopRunInput;
        let acknowledgementConversationId: string;
        let acknowledgementMessageId: string;
        let acknowledgementDeliveryMode: RunInputDelivery;
        let acknowledgementQueuePosition: number | null | undefined;
        if (config.mode === 'cloud') {
          if (!activityAuthorityAdapter.client || !activityAuthorityScope) {
            throw new Error('cloud_run_input_authority_scope_unavailable');
          }
          const acknowledgement =
            await activityAuthorityAdapter.client.createRunInput(
              activityAuthorityScope,
              currentArtifactRun.id,
              {
                expected_run_revision: currentArtifactRun.revision,
                message: content,
                message_id: request.messageId,
                idempotency_key: request.idempotencyKey,
                delivery: requestedDelivery,
                references: outgoingReferences.map((reference) => ({
                  ...reference,
                })),
                context_items: contextItems.map((item) => ({
                  ...item,
                  metadata: item.metadata ? { ...item.metadata } : null,
                })),
              },
            );
          acknowledgementInput = desktopRunInputFromCloud(
            acknowledgement.input,
          );
          acknowledgementConversationId = acknowledgement.conversation_id;
          acknowledgementMessageId = acknowledgement.message_id;
          acknowledgementDeliveryMode = acknowledgement.delivery_mode;
          acknowledgementQueuePosition = acknowledgement.queue_position;
        } else {
          const acknowledgement = await api.createRunInput(
            currentArtifactRun.id,
            {
              expectedRunRevision: currentArtifactRun.revision,
              message: content,
              messageId: request.messageId,
              idempotencyKey: request.idempotencyKey,
              delivery: requestedDelivery,
              references: outgoingReferences,
              contextItems,
            },
          );
          acknowledgementInput = acknowledgement.input;
          acknowledgementConversationId = acknowledgement.conversation_id;
          acknowledgementMessageId = acknowledgement.message_id;
          acknowledgementDeliveryMode = acknowledgement.delivery_mode;
          acknowledgementQueuePosition = acknowledgement.queue_position;
        }
        onWorkspaceMessageSaved?.();
        if (!referencesOverride) setRunInputReferences([]);
        setRunInputs((current) =>
          [
            ...current.filter((input) => input.id !== acknowledgementInput.id),
            acknowledgementInput,
          ].sort((left, right) => left.sequence - right.sequence),
        );
        runInputRequestRef.current = null;
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
            config.projectId,
          );
        }
        return;
      }
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
        onWorkspaceMessageSaved?.();
        return;
      }
      const saved = await api.sendMessage(
        content,
        undefined,
        contextItems,
        mentions,
      );
      setDataset((current) => ({
        ...current,
        messages: [...current.messages, saved],
      }));
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
    } catch (caught) {
      const detail = formatConnectionError(caught, config.apiBaseUrl);
      setError(detail);
      upsertAgentTaskSignal({
        id: signalId,
        status: 'failed',
        detail,
      });
    } finally {
      setSending(false);
    }
  };
  return {
    sendMessageContent,
  };
}
