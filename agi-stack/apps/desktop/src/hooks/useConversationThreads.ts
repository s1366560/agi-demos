import { useI18n } from '../i18n';
import {
  DesktopApiClient,
} from '../api/client';
import {
  isCurrentContextRevision,
  isSameDesktopRequestScope,
} from '../features/auth/authContextModel';
import {
  composerAgentExecutionContext,
} from '../features/chat/chatComposerModel';
import {
  canonicalJsonSha256,
} from '../features/session/canonicalJsonDigest';
import {
  type NewTaskAgentTurnInput,
  type NewTaskResumeDraft,
  type NewTaskSession,
} from '../features/task/NewTaskFlow';
import {
  type NewThreadComposerInput,
} from '../features/task/NewThreadComposer';
import {
  buildPlanningPrompt,
  newTaskAgentTurnTransport,
  type NewTaskAgentTurnOutcome,
  type NewTaskDefinition,
} from '../features/task/newTaskPlanModel';
import {
  browserTaskSessionCreationStorage,
  buildRuntimeTaskSessionRequest,
  clearTaskSessionCreationAttempt,
  readTaskSessionCreationAttempt,
  taskSessionCreationAttempt,
  taskSessionCreationFingerprint,
  writeTaskSessionCreationAttempt,
} from '../features/task/newTaskSessionModel';
import {
  UNBOUND_CONVERSATIONS_KEY,
} from '../features/workspace/workspaceTreeModel';
import {
  AgentConversation,
  DesktopRuntimeConfig,
} from '../types';
import {
  formatConnectionError,
} from '../utils/format';
import {
  agentConversationScopeKeyFor,
} from '../appShellTypes';
import type { AgentConversationParams } from './useAgentConversation';

export function useConversationThreads(params: AgentConversationParams) {
  const { t } = useI18n();
  const {
    config,
    auth,
    connection,
    dataset,
    sessionProjection,
    sessionTaskListPlanRecovery,
    newThreadWorkspaces,
    configuredNewThreadWorkspaceId,
    canManageWorkspacePolicy,
    socket,
    workspaceAgentPolicy,
    setLoginModalOpen,
    setCommandPaletteOpen,
    setNewTaskOpen,
    setNewTaskPreferredWorkspaceId,
    setNewTaskResumeDraft,
    setNewThreadScope,
    setNewThreadCreating,
    setNewThreadError,
    setCommandQuery,
    setExpandedWorkspaceIds,
    setDataset,
    setError,
    setSectionBackStack,
    setSectionForwardStack,
    setReviewTab,
    setSelectedTaskId,
    setAgentConversationSession,
    setAgentTaskSignals,
    pendingNewTaskAgentTurnsRef,
    contextRevisionRef,
    configRef,
    configScopeEpochRef,
    commitRuntimeConfig,
    upsertAgentTaskSignal,
    resetConversationTimeline,
    loadConversationTimeline,
    applySectionSideEffects,
    switchSection,
  } = params;
  const openNewTask = (
    workspaceId = config.workspaceId,
    resumeDraft: NewTaskResumeDraft | null = null,
  ) => {
    setError(null);
    setLoginModalOpen(false);
    setCommandPaletteOpen(false);
    setCommandQuery('');
    setNewTaskPreferredWorkspaceId(workspaceId);
    setNewTaskResumeDraft(resumeDraft);
    setNewTaskOpen(true);
  };

  const startNewSession = () => {
    setNewThreadError(null);
    setNewThreadScope({
      projectId: config.projectId,
      workspaceId: configuredNewThreadWorkspaceId,
    });
    switchSection('home');
  };

  const changeNewThreadWorkspace = (workspaceId: string) => {
    const nextWorkspaceId = workspaceId.trim();
    if (
      nextWorkspaceId &&
      !newThreadWorkspaces.some((workspace) => workspace.id === nextWorkspaceId)
    ) {
      setNewThreadError(t('task.workspaceSelectionStale'));
      return;
    }
    setNewThreadError(null);
    setNewThreadScope({
      projectId: config.projectId,
      workspaceId: nextWorkspaceId,
    });
  };

  const resumeSessionTaskListReview = () => {
    const projection = sessionProjection;
    if (
      projection?.planAuthority.kind !== 'agent_task_list' ||
      !sessionTaskListPlanRecovery?.canResume
    ) {
      setError(t('session.authorityActionUnavailable'));
      return;
    }
    const conversation = projection.conversation;
    const workspaceId =
      conversation.workspace_id?.trim() || config.workspaceId.trim();
    const workspace = (
      dataset.workspacesByProject[conversation.project_id] ?? dataset.workspaces
    ).find((item) => item.id === workspaceId);
    const tasks = sessionTaskListPlanRecovery.tasks;
    if (!workspace || !workspaceId || !tasks) {
      setError(t('session.authorityActionUnavailable'));
      return;
    }
    const capabilityMode = conversation.agent_config?.capability_mode;
    const kind =
      capabilityMode === 'code' || conversation.conversation_mode === 'code'
        ? 'programming'
        : 'general';
    const sessionConfig = {
      ...config,
      tenantId: conversation.tenant_id || config.tenantId,
      projectId: conversation.project_id,
      workspaceId,
    };
    const resumeDraft: NewTaskResumeDraft = {
      session: { workspace, conversation, config: sessionConfig },
      definition: {
        title: conversation.title,
        objective:
          conversation.summary?.trim() ||
          workspace.description?.trim() ||
          conversation.title,
        kind,
        workspaceRoot: config.workspaceRoot,
        contextSources: ['project_memory', 'project_files'],
      },
      tasks,
    };
    openNewTask(workspaceId, resumeDraft);
  };

  const persistNewTaskSession = (session: NewTaskSession) => {
    const { workspace, conversation, config: sessionConfig } = session;
    setDataset((current) => ({
      ...current,
      workspaces: [
        workspace,
        ...current.workspaces.filter((item) => item.id !== workspace.id),
      ],
      workspacesByProject: {
        ...current.workspacesByProject,
        [sessionConfig.projectId]: [
          workspace,
          ...(
            current.workspacesByProject[sessionConfig.projectId] ?? []
          ).filter((item) => item.id !== workspace.id),
        ],
      },
      conversationsByWorkspace: {
        ...current.conversationsByWorkspace,
        [workspace.id]: [
          conversation,
          ...(current.conversationsByWorkspace[workspace.id] ?? []).filter(
            (item) => item.id !== conversation.id,
          ),
        ],
      },
    }));
  };

  const activateNewTaskSession = (session: NewTaskSession) => {
    const { workspace, conversation, config: sessionConfig } = session;
    setSelectedTaskId('');
    resetConversationTimeline();
    setAgentTaskSignals([]);
    setReviewTab('plan');
    setSectionBackStack([]);
    setSectionForwardStack([]);
    persistNewTaskSession(session);
    commitRuntimeConfig(sessionConfig);
    setAgentConversationSession({
      scopeKey: agentConversationScopeKeyFor(
        sessionConfig.projectId,
        workspace.id,
      ),
      conversation,
    });
    setExpandedWorkspaceIds((current) => new Set([...current, workspace.id]));
    applySectionSideEffects('chat');
    void loadConversationTimeline(conversation, sessionConfig.projectId);
  };

  const activateUnboundNewThread = (
    conversation: AgentConversation,
    threadConfig: DesktopRuntimeConfig,
  ) => {
    setSelectedTaskId('');
    resetConversationTimeline();
    setAgentTaskSignals([]);
    setReviewTab('overview');
    setSectionBackStack([]);
    setSectionForwardStack([]);
    setDataset((current) => ({
      ...current,
      conversationsByWorkspace: {
        ...current.conversationsByWorkspace,
        [UNBOUND_CONVERSATIONS_KEY]: [
          conversation,
          ...(
            current.conversationsByWorkspace[UNBOUND_CONVERSATIONS_KEY] ?? []
          ).filter((item) => item.id !== conversation.id),
        ],
      },
    }));
    commitRuntimeConfig(threadConfig);
    setAgentConversationSession({
      scopeKey: agentConversationScopeKeyFor(threadConfig.projectId, ''),
      conversation,
    });
    applySectionSideEffects('chat');
    void loadConversationTimeline(
      conversation,
      threadConfig.projectId,
      threadConfig,
    );
  };

  const runNewTaskAgentTurn = async (
    input: NewTaskAgentTurnInput,
    delivery: { deferUntilNextConnection?: boolean } = {},
  ): Promise<NewTaskAgentTurnOutcome> => {
    const acknowledgment = new Promise<NewTaskAgentTurnOutcome>(
      (resolve, reject) => {
        const timeoutId = window.setTimeout(() => {
          pendingNewTaskAgentTurnsRef.current.delete(input.messageId);
          resolve('unknown_outcome');
        }, 10_000);
        pendingNewTaskAgentTurnsRef.current.set(input.messageId, {
          conversationId: input.conversationId,
          messageId: input.messageId,
          timeoutId,
          resolve,
          reject,
        });
      },
    );
    const clearPendingAgentTurn = () => {
      const pending = pendingNewTaskAgentTurnsRef.current.get(input.messageId);
      if (!pending) return;
      window.clearTimeout(pending.timeoutId);
      pendingNewTaskAgentTurnsRef.current.delete(input.messageId);
    };
    const queued = socket.sendAgentMessage({
      conversationId: input.conversationId,
      projectId: input.projectId,
      message: input.message,
      messageId: input.messageId,
      deferUntilNextConnection: delivery.deferUntilNextConnection,
      agentId: input.agentId,
      forcedSkillName: input.forcedSkillName,
      subAgentId: input.subAgentId,
      mentions: input.mentions,
      fileMetadata: input.fileMetadata,
      appModelContext: input.appModelContext,
    });
    const transport = newTaskAgentTurnTransport(input.config.mode, queued);
    if (transport === 'socket') {
      return acknowledgment;
    }
    clearPendingAgentTurn();
    if (transport === 'local_http') {
      const client = new DesktopApiClient(input.config);
      await client.runAgentMessage(
        input.conversationId,
        input.message,
        input.messageId,
        input.projectId,
        undefined,
        input,
      );
      return 'acknowledged';
    }
    throw new Error(t('task.liveConnectionRequired'));
  };

  const createComposerThread = async (input: NewThreadComposerInput) => {
    const actorId = auth.user?.user_id.trim() ?? '';
    const workspaceId = input.workspaceId.trim();
    const title = input.prompt.split(/\r?\n/, 1)[0].trim().slice(0, 96);
    if (!actorId || !title) {
      setNewThreadError(t('task.creationContextUnavailable'));
      return;
    }
    const requestConfig = configRef.current;
    const expectedContextRevision = contextRevisionRef.current;
    const expectedScopeEpoch = configScopeEpochRef.current;
    const threadConfig = { ...requestConfig, workspaceId };
    let activatedConfig: DesktopRuntimeConfig | null = null;
    let activatedScopeEpoch: number | null = null;
    const requestScopeIsCurrent = () =>
      isCurrentContextRevision(
        expectedContextRevision,
        contextRevisionRef.current,
      ) &&
      expectedScopeEpoch === configScopeEpochRef.current &&
      isSameDesktopRequestScope(requestConfig, configRef.current);
    const activatedScopeIsCurrent = () =>
      activatedConfig !== null &&
      activatedScopeEpoch !== null &&
      isCurrentContextRevision(
        expectedContextRevision,
        contextRevisionRef.current,
      ) &&
      activatedScopeEpoch === configScopeEpochRef.current &&
      isSameDesktopRequestScope(activatedConfig, configRef.current);
    const creationScopeIsCurrent = () =>
      activatedConfig === null
        ? requestScopeIsCurrent()
        : activatedScopeIsCurrent();

    if (!workspaceId) {
      if (threadConfig.mode === 'cloud' && connection !== 'ready') {
        setNewThreadError(t('task.liveConnectionRequired'));
        return;
      }
      let activatedConversation: AgentConversation | null = null;
      let firstMessageId = '';
      let firstSignalId = '';
      setNewThreadCreating(true);
      setNewThreadError(null);
      setError(null);
      try {
        const client = new DesktopApiClient(threadConfig);
        const conversation = await client.createAgentConversation(
          title,
          threadConfig.projectId,
          actorId,
          input.mode,
          input.model
            ? {
                llm_model_override: input.model.modelId,
                ...(threadConfig.mode === 'local'
                  ? {
                      llm_route_override: {
                        provider_id: input.model.providerId,
                        model_id: input.model.modelId,
                      },
                    }
                  : {}),
              }
            : undefined,
        );
        if (!requestScopeIsCurrent()) return;
        if (conversation.workspace_id !== null) {
          throw new Error(t('task.unboundConversationScopeMismatch'));
        }
        activateUnboundNewThread(conversation, threadConfig);
        activatedConfig = threadConfig;
        activatedScopeEpoch = configScopeEpochRef.current;
        activatedConversation = conversation;
        const execution = composerAgentExecutionContext(
          input.prompt,
          input.contextItems,
        );
        firstMessageId = `desktop-thread-${crypto.randomUUID()}`;
        firstSignalId = `agent-task-${firstMessageId}`;
        upsertAgentTaskSignal({
          id: firstSignalId,
          conversationId: conversation.id,
          messageId: firstMessageId,
          content: input.prompt,
          status: 'queued',
          detail: 'Agent conversation opened. Sending the first turn.',
        });
        const outcome = await runNewTaskAgentTurn(
          {
            config: threadConfig,
            conversationId: conversation.id,
            projectId: threadConfig.projectId,
            message: execution.message,
            messageId: firstMessageId,
            agentId: execution.agentId,
            forcedSkillName: execution.forcedSkillName,
            subAgentId: execution.subAgentId,
            mentions: execution.mentions,
            fileMetadata: execution.fileMetadata,
            appModelContext: execution.appModelContext,
          },
          {
            deferUntilNextConnection: !isSameDesktopRequestScope(
              requestConfig,
              threadConfig,
            ),
          },
        );
        if (!activatedScopeIsCurrent()) return;
        upsertAgentTaskSignal({
          id: firstSignalId,
          status: outcome === 'acknowledged' ? 'acknowledged' : 'queued',
          detail:
            outcome === 'acknowledged'
              ? 'Agent acknowledged the first turn.'
              : 'The first turn was sent, but acknowledgement is still pending.',
        });
      } catch (caught) {
        if (!creationScopeIsCurrent()) return;
        const detail = formatConnectionError(caught, threadConfig.apiBaseUrl);
        setNewThreadError(detail);
        setError(detail);
        if (activatedConversation && firstMessageId && firstSignalId) {
          upsertAgentTaskSignal({
            id: firstSignalId,
            conversationId: activatedConversation.id,
            messageId: firstMessageId,
            content: input.prompt,
            status: 'failed',
            detail,
          });
        }
      } finally {
        setNewThreadCreating(false);
      }
      return;
    }

    const expectedPolicyScopeKey = [
      threadConfig.mode,
      threadConfig.apiBaseUrl,
      threadConfig.tenantId,
      threadConfig.projectId,
      workspaceId,
    ].join('\u0000');
    const policy = workspaceAgentPolicy.policy;
    if (
      workspaceAgentPolicy.loading ||
      workspaceAgentPolicy.scopeKey !== expectedPolicyScopeKey ||
      !policy ||
      !input.model
    ) {
      setNewThreadError(t('task.creationContextUnavailable'));
      return;
    }
    const definition: NewTaskDefinition = {
      title,
      objective: input.prompt,
      kind: input.mode === 'code' ? 'programming' : 'general',
      workspaceRoot: requestConfig.workspaceRoot,
      contextSources: ['project_memory', 'project_files'],
    };
    const policySelection =
      canManageWorkspacePolicy && !workspaceAgentPolicy.compatibilityMode
        ? {
            expected_revision: policy.revision,
            route: {
              provider_id: input.model.providerId,
              model_id: input.model.modelId,
            },
            reasoning_effort: input.reasoningEffort,
            permission_mode: input.permissionMode,
          }
        : undefined;
    const baseFingerprint = taskSessionCreationFingerprint(
      threadConfig,
      actorId,
      definition,
      workspaceId,
    );
    const policyDigest = canonicalJsonSha256({
      baseFingerprint,
      policySelection,
      contextItems: input.contextItems,
    });
    const fingerprint = policyDigest ? `sha256:${policyDigest}` : '';
    const storage = browserTaskSessionCreationStorage();
    const storedAttempt = readTaskSessionCreationAttempt(storage, fingerprint);
    const attempt = taskSessionCreationAttempt(
      storedAttempt,
      fingerprint,
      () => `desktop-task-session-${crypto.randomUUID()}`,
    );
    if (!fingerprint || !writeTaskSessionCreationAttempt(storage, attempt)) {
      setNewThreadError(t('task.creationRecoveryUnavailable'));
      return;
    }

    setNewThreadCreating(true);
    setNewThreadError(null);
    try {
      const client = new DesktopApiClient(threadConfig);
      const request = buildRuntimeTaskSessionRequest(
        threadConfig.mode,
        definition,
        workspaceId,
        attempt.idempotencyKey,
        input.contextItems,
        policySelection,
      );
      const result = await client.createTaskSession(request);
      clearTaskSessionCreationAttempt(storage, fingerprint);
      if (!requestScopeIsCurrent()) return;
      const session: NewTaskSession = {
        workspace: result.workspace,
        conversation: result.conversation,
        config: { ...threadConfig, workspaceId: result.workspace.id },
      };
      if (result.policy) workspaceAgentPolicy.acceptPolicy(result.policy);
      activateNewTaskSession(session);
      activatedConfig = session.config;
      activatedScopeEpoch = configScopeEpochRef.current;
      const execution = composerAgentExecutionContext(
        buildPlanningPrompt(definition),
        input.contextItems,
      );
      await runNewTaskAgentTurn(
        {
          config: session.config,
          conversationId: session.conversation.id,
          projectId: session.config.projectId,
          message: execution.message,
          messageId: `desktop-plan-${crypto.randomUUID()}`,
          agentId: execution.agentId,
          forcedSkillName: execution.forcedSkillName,
          subAgentId: execution.subAgentId,
          mentions: execution.mentions,
          fileMetadata: execution.fileMetadata,
          appModelContext: execution.appModelContext,
        },
        {
          deferUntilNextConnection: !isSameDesktopRequestScope(
            requestConfig,
            session.config,
          ),
        },
      );
    } catch (caught) {
      if (!creationScopeIsCurrent()) return;
      setNewThreadError(
        caught instanceof Error ? caught.message : String(caught),
      );
    } finally {
      setNewThreadCreating(false);
    }
  };
  return {
    activateNewTaskSession,
    changeNewThreadWorkspace,
    createComposerThread,
    openNewTask,
    persistNewTaskSession,
    resumeSessionTaskListReview,
    runNewTaskAgentTurn,
    startNewSession,
  };
}
