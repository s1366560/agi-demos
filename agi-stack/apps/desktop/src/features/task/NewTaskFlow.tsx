import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Theme } from '@radix-ui/themes';
import {
  ArrowRightIcon,
  Cross2Icon,
  MagicWandIcon,
} from '@radix-ui/react-icons';

import { DesktopApiClient } from '../../api/client';
import { useI18n } from '../../i18n';
import type {
  AgentConversation,
  AgentPlanApprovalCapability,
  AgentPlanTask,
  DesktopExecutionEnvironmentKind,
  DesktopPermissionProfile,
  DesktopPlanVersion,
  DesktopRuntimeConfig,
  WorkspaceSummary,
} from '../../types';
import {
  approvalCapability,
  approvalPlanVersion,
  canApprovePlan,
  defaultPermissionProfile,
  hasPlanVersionChanged,
  isPlanApprovalBlocked,
  legacyPlanMatchesPreview,
} from './newTaskApprovalModel';
import {
  buildExecutionPrompt,
  buildPlanReplacementPrompt,
  buildPlanningPrompt,
  buildRevisionPrompt,
  createReviewPlanDraft,
  enabledReviewPlanSteps,
  hasReviewPlanChanges,
  orderedPlanTasks,
  planTaskSignature,
  shouldOfferPlanRetry,
  type NewTaskContextSource,
  type NewTaskDefinition,
  type NewTaskKind,
  type ReviewPlanStep,
} from './newTaskPlanModel';
import {
  NewTaskDefinitionStage,
  NewTaskPlanningStage,
  NewTaskReviewStage,
} from './NewTaskFlowStages';
import { FlowStep, NewTaskFooterBackButton } from './NewTaskStagePrimitives';
import './NewTaskFlow.css';
import './NewTaskPlanReview.css';

type NewTaskFlowPhase = 'define' | 'planning' | 'review' | 'launching';

export type NewTaskSession = {
  workspace: WorkspaceSummary;
  conversation: AgentConversation;
  config: DesktopRuntimeConfig;
};

export type NewTaskAgentTurnInput = {
  config: DesktopRuntimeConfig;
  conversationId: string;
  projectId: string;
  message: string;
  messageId: string;
};

type NewTaskFlowProps = {
  open: boolean;
  config: DesktopRuntimeConfig;
  workspaces: WorkspaceSummary[];
  preferredWorkspaceId?: string;
  preferredKind?: NewTaskKind;
  disabledReason?: string | null;
  onClose: () => void;
  onSessionReady: (session: NewTaskSession) => void;
  onRunAgentTurn: (input: NewTaskAgentTurnInput) => Promise<void>;
  onError: (message: string) => void;
};

const NEW_WORKSPACE_VALUE = '__new_workspace__';
const PLAN_POLL_INTERVAL_MS = 1_500;
const DEFAULT_CONTEXT_SOURCES: NewTaskContextSource[] = [
  'project_memory',
  'project_files',
];

export function NewTaskFlow({
  open,
  config,
  workspaces,
  preferredWorkspaceId,
  preferredKind,
  disabledReason,
  onClose,
  onSessionReady,
  onRunAgentTurn,
  onError,
}: NewTaskFlowProps) {
  const { t } = useI18n();
  const [phase, setPhase] = useState<NewTaskFlowPhase>('define');
  const [title, setTitle] = useState('');
  const [objective, setObjective] = useState('');
  const [kind, setKind] = useState<NewTaskKind>(preferredKind ?? 'general');
  const [contextSources, setContextSources] = useState<NewTaskContextSource[]>(
    DEFAULT_CONTEXT_SOURCES,
  );
  const [environmentKind, setEnvironmentKind] =
    useState<DesktopExecutionEnvironmentKind>('local');
  const [permissionProfile, setPermissionProfile] =
    useState<DesktopPermissionProfile>('read_only');
  const [workspaceRoot, setWorkspaceRoot] = useState(config.workspaceRoot);
  const [workspaceSelection, setWorkspaceSelection] = useState(
    preferredWorkspaceId || config.workspaceId || NEW_WORKSPACE_VALUE,
  );
  const [planTasks, setPlanTasks] = useState<AgentPlanTask[]>([]);
  const [reviewSteps, setReviewSteps] = useState<ReviewPlanStep[]>([]);
  const [planVersion, setPlanVersion] = useState<DesktopPlanVersion | null>(null);
  const [planApproval, setPlanApproval] =
    useState<AgentPlanApprovalCapability | null>(null);
  const [planRequiresReview, setPlanRequiresReview] = useState(false);
  const [revisionAwaitingPlan, setRevisionAwaitingPlan] = useState(false);
  const [manualPlanReviewRequired, setManualPlanReviewRequired] = useState(false);
  const [planRetryAvailable, setPlanRetryAvailable] = useState(false);
  const [revisionFeedback, setRevisionFeedback] = useState('');
  const [revisionComposerOpen, setRevisionComposerOpen] = useState(false);
  const [flowError, setFlowError] = useState<string | null>(null);
  const [session, setSession] = useState<NewTaskSession | null>(null);
  const expectedPlanSignatureRef = useRef('');
  const displayedPlanSignatureRef = useRef('');
  const displayedPlanVersionRef = useRef<DesktopPlanVersion | null>(null);
  const lastPlanningPromptRef = useRef('');
  const emptyPlanPollCountRef = useRef(0);
  const flowEpochRef = useRef(0);
  const wasOpenRef = useRef(false);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const onCloseRef = useRef(onClose);
  const approvalAttemptRef = useRef<{ identity: string; id: string } | null>(null);
  const titleInputRef = useRef<HTMLInputElement>(null);
  onCloseRef.current = onClose;

  const selectedWorkspace = useMemo(
    () => workspaces.find((workspace) => workspace.id === workspaceSelection) ?? null,
    [workspaceSelection, workspaces],
  );
  const orderedTasks = useMemo(() => orderedPlanTasks(planTasks), [planTasks]);
  const reviewDirty = useMemo(
    () => hasReviewPlanChanges(orderedTasks, reviewSteps),
    [orderedTasks, reviewSteps],
  );
  const enabledStepCount = enabledReviewPlanSteps(reviewSteps).length;
  const approvalReady =
    canApprovePlan(
      planApproval,
      planVersion,
      isPlanApprovalBlocked(
        planRequiresReview || manualPlanReviewRequired,
        revisionAwaitingPlan,
      ),
      orderedTasks.length,
    ) &&
    !reviewDirty &&
    enabledStepCount > 0;
  const canGenerate =
    title.trim().length > 0 &&
    objective.trim().length > 0 &&
    contextSources.length > 0 &&
    Boolean(config.projectId.trim()) &&
    !disabledReason;
  const workspaceLabel =
    selectedWorkspace?.name ||
    selectedWorkspace?.title ||
    (workspaceSelection === NEW_WORKSPACE_VALUE
      ? t('task.createWorkspace')
      : workspaceSelection);

  useEffect(() => {
    if (wasOpenRef.current === open) return;
    wasOpenRef.current = open;
    flowEpochRef.current += 1;
    if (!open) return;
    const nextKind = preferredKind ?? 'general';
    setPhase('define');
    setTitle('');
    setObjective('');
    setKind(nextKind);
    setContextSources(DEFAULT_CONTEXT_SOURCES);
    setEnvironmentKind(nextKind === 'programming' ? 'worktree' : 'local');
    setPermissionProfile(defaultPermissionProfile(nextKind));
    setWorkspaceRoot(config.workspaceRoot);
    setWorkspaceSelection(preferredWorkspaceId || config.workspaceId || NEW_WORKSPACE_VALUE);
    setPlanTasks([]);
    setReviewSteps([]);
    setPlanVersion(null);
    setPlanApproval(null);
    setPlanRequiresReview(false);
    setRevisionAwaitingPlan(false);
    setManualPlanReviewRequired(false);
    setPlanRetryAvailable(false);
    setRevisionFeedback('');
    setRevisionComposerOpen(false);
    setFlowError(null);
    setSession(null);
    expectedPlanSignatureRef.current = '';
    displayedPlanSignatureRef.current = '';
    displayedPlanVersionRef.current = null;
    lastPlanningPromptRef.current = '';
    emptyPlanPollCountRef.current = 0;
    approvalAttemptRef.current = null;
    window.setTimeout(() => titleInputRef.current?.focus(), 0);
  }, [config.workspaceId, config.workspaceRoot, open, preferredKind, preferredWorkspaceId]);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        flowEpochRef.current += 1;
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      window.setTimeout(() => previousFocusRef.current?.focus(), 0);
    };
  }, [open]);

  useEffect(() => {
    if (!open || (phase !== 'planning' && phase !== 'review') || !session) return;
    const abortController = new AbortController();
    let stopped = false;
    let pollTimeout: number | undefined;

    const scheduleNextPoll = () => {
      if (stopped) return;
      pollTimeout = window.setTimeout(loadPlan, PLAN_POLL_INTERVAL_MS);
    };

    const loadPlan = async () => {
      try {
        const client = new DesktopApiClient(session.config);
        const response = await client.listAgentPlanTasks(
          session.conversation.id,
          abortController.signal,
        );
        if (stopped) return;
        const nextApproval = approvalCapability(response);
        const nextPlanVersion = approvalPlanVersion(response);
        const tasks = orderedPlanTasks(
          nextPlanVersion?.tasks?.length ? nextPlanVersion.tasks : (response.tasks ?? []),
        );
        const signature = planTaskSignature(tasks);
        const previousSignature = displayedPlanSignatureRef.current;
        const versionChanged = hasPlanVersionChanged(
          displayedPlanVersionRef.current,
          nextPlanVersion,
        );
        const tasksChanged = Boolean(previousSignature) && signature !== previousSignature;
        const isNewPlanningResult =
          phase === 'planning' &&
          (versionChanged || signature !== expectedPlanSignatureRef.current);
        const isNewReviewResult = phase === 'review' && (versionChanged || tasksChanged);

        if (tasks.length > 0) {
          setPlanApproval(nextApproval);
          setPlanVersion(nextPlanVersion);
        }
        if (phase === 'planning' && !isNewPlanningResult) {
          emptyPlanPollCountRef.current += 1;
          if (shouldOfferPlanRetry(emptyPlanPollCountRef.current)) {
            setPlanRetryAvailable(true);
          }
        }
        if (tasks.length > 0 && (isNewPlanningResult || isNewReviewResult)) {
          emptyPlanPollCountRef.current = 0;
          setPlanRetryAvailable(false);
          displayedPlanSignatureRef.current = signature;
          displayedPlanVersionRef.current = nextPlanVersion;
          setPlanTasks(tasks);
          setReviewSteps(createReviewPlanDraft(tasks));
          setPlanRequiresReview(phase === 'review');
          setRevisionAwaitingPlan(false);
          setManualPlanReviewRequired(false);
          setRevisionFeedback('');
          setRevisionComposerOpen(false);
          setFlowError(null);
          setPhase('review');
        }
        scheduleNextPoll();
      } catch (error) {
        if (stopped || abortController.signal.aborted) return;
        setFlowError(error instanceof Error ? error.message : String(error));
        if (phase === 'planning') {
          emptyPlanPollCountRef.current += 1;
          if (shouldOfferPlanRetry(emptyPlanPollCountRef.current)) {
            setPlanRetryAvailable(true);
          }
        }
        scheduleNextPoll();
      }
    };

    void loadPlan();
    return () => {
      stopped = true;
      if (pollTimeout !== undefined) window.clearTimeout(pollTimeout);
      abortController.abort();
    };
  }, [open, phase, session]);

  if (!open) return null;

  const closeFlow = () => {
    flowEpochRef.current += 1;
    onClose();
  };

  const runAgentTurn = async (
    targetSession: NewTaskSession,
    message: string,
    messageId: string,
  ) => {
    await onRunAgentTurn({
      config: targetSession.config,
      conversationId: targetSession.conversation.id,
      projectId: targetSession.config.projectId,
      message,
      messageId,
    });
  };

  const generatePlan = async () => {
    if (!canGenerate) return;
    const operationEpoch = flowEpochRef.current;
    setPhase('planning');
    setFlowError(null);
    setRevisionAwaitingPlan(false);
    setManualPlanReviewRequired(false);
    setPlanRetryAvailable(false);
    emptyPlanPollCountRef.current = 0;
    const definition: NewTaskDefinition = {
      title,
      objective,
      kind,
      workspaceRoot,
      contextSources,
    };
    const planningPrompt = buildPlanningPrompt(definition);
    lastPlanningPromptRef.current = planningPrompt;
    try {
      const baseClient = new DesktopApiClient(config);
      const workspace =
        selectedWorkspace ??
        (await baseClient.createWorkspaceForProject(
          config.projectId,
          title.trim(),
          objective.trim(),
          config.tenantId,
          {
            useCase: kind,
            collaborationMode: 'multi_agent_shared',
            sandboxCodeRoot: kind === 'programming' ? workspaceRoot.trim() : undefined,
          },
        ));
      const scopedConfig = { ...config, workspaceId: workspace.id };
      const client = new DesktopApiClient(scopedConfig);
      const created = await client.createAgentConversation(
        title.trim(),
        config.projectId,
        kind === 'programming' ? 'code' : 'work',
      );
      const conversation = await client.updateAgentConversationMode(
        created.id,
        { workspace_id: workspace.id },
        config.projectId,
      );
      await client.switchPlanMode(conversation.id, 'plan');
      await client.sendMessage(objective.trim());
      const readySession = { workspace, conversation, config: scopedConfig };
      await runAgentTurn(
        readySession,
        planningPrompt,
        `desktop-plan-${crypto.randomUUID()}`,
      );
      if (flowEpochRef.current !== operationEpoch) return;
      setSession(readySession);
      onSessionReady(readySession);
    } catch (error) {
      if (flowEpochRef.current !== operationEpoch) return;
      const message = error instanceof Error ? error.message : String(error);
      setFlowError(message);
      setPhase('define');
      onError(message);
    }
  };

  const requestRevision = async (agentPrompt?: string, workspaceMessage?: string) => {
    const feedback = revisionFeedback.trim();
    const prompt = agentPrompt ?? buildRevisionPrompt(feedback);
    const humanMessage = workspaceMessage ?? feedback;
    if (!session || !prompt || !humanMessage) return;
    const operationEpoch = flowEpochRef.current;
    expectedPlanSignatureRef.current = planTaskSignature(planTasks);
    lastPlanningPromptRef.current = prompt;
    setRevisionAwaitingPlan(true);
    setManualPlanReviewRequired(false);
    setPlanRetryAvailable(false);
    emptyPlanPollCountRef.current = 0;
    setRevisionComposerOpen(false);
    setFlowError(null);
    setPhase('planning');
    try {
      const client = new DesktopApiClient(session.config);
      await client.sendMessage(humanMessage);
      await runAgentTurn(
        session,
        prompt,
        `desktop-plan-revision-${crypto.randomUUID()}`,
      );
    } catch (error) {
      if (flowEpochRef.current !== operationEpoch) return;
      const message = error instanceof Error ? error.message : String(error);
      setFlowError(message);
      if (!agentPrompt) setRevisionComposerOpen(true);
      setPhase('review');
      onError(message);
    }
  };

  const retryPlanning = async () => {
    const prompt = lastPlanningPromptRef.current;
    if (!session || !prompt) return;
    const operationEpoch = flowEpochRef.current;
    setPlanRetryAvailable(false);
    emptyPlanPollCountRef.current = 0;
    setFlowError(null);
    try {
      await runAgentTurn(
        session,
        prompt,
        `desktop-plan-retry-${crypto.randomUUID()}`,
      );
    } catch (error) {
      if (flowEpochRef.current !== operationEpoch) return;
      const message = error instanceof Error ? error.message : String(error);
      setFlowError(message);
      setPlanRetryAvailable(true);
      onError(message);
    }
  };

  const stopWaitingForRevision = () => {
    setRevisionAwaitingPlan(false);
    setManualPlanReviewRequired(true);
    setReviewSteps(createReviewPlanDraft(orderedTasks));
    setRevisionFeedback('');
    setRevisionComposerOpen(false);
    setPlanRetryAvailable(false);
    setFlowError(null);
  };

  const refreshLegacyPlanBeforeApproval = async (operationEpoch: number): Promise<boolean> => {
    if (!session) return false;
    const client = new DesktopApiClient(session.config);
    const response = await client.listAgentPlanTasks(session.conversation.id);
    if (flowEpochRef.current !== operationEpoch) return false;
    const tasks = orderedPlanTasks(response.tasks ?? []);
    const samePlan = legacyPlanMatchesPreview(response, displayedPlanSignatureRef.current);
    if (samePlan) return true;
    setPlanApproval(approvalCapability(response));
    setPlanVersion(approvalPlanVersion(response));
    setPlanTasks(tasks);
    setReviewSteps(createReviewPlanDraft(tasks));
    displayedPlanSignatureRef.current = planTaskSignature(tasks);
    setPlanRequiresReview(true);
    setManualPlanReviewRequired(false);
    setFlowError(t('task.planChangedBeforeApproval'));
    return false;
  };

  const approveLegacyPlan = async (
    activeSession: NewTaskSession,
    operationEpoch: number,
  ): Promise<boolean> => {
    const client = new DesktopApiClient(activeSession.config);
    if (!(await refreshLegacyPlanBeforeApproval(operationEpoch))) return false;
    if (flowEpochRef.current !== operationEpoch) return false;
    await client.switchPlanMode(activeSession.conversation.id, 'build');
    try {
      await runAgentTurn(
        activeSession,
        buildExecutionPrompt(),
        `desktop-build-${crypto.randomUUID()}`,
      );
    } catch (error) {
      try {
        await client.switchPlanMode(activeSession.conversation.id, 'plan');
      } catch {
        throw new Error(t('task.legacyRollbackFailed'));
      }
      throw error;
    }
    return true;
  };

  const approveVersionedPlan = async (
    activeSession: NewTaskSession,
    previewedPlanVersion: DesktopPlanVersion,
  ) => {
    const client = new DesktopApiClient(activeSession.config);
    const approvalIdentity = [
      previewedPlanVersion.id,
      previewedPlanVersion.version,
      permissionProfile,
      environmentKind,
    ].join(':');
    if (approvalAttemptRef.current?.identity !== approvalIdentity) {
      approvalAttemptRef.current = { identity: approvalIdentity, id: crypto.randomUUID() };
    }
    const approvalId = approvalAttemptRef.current.id;
    return client.approvePlanAndStart({
      conversationId: activeSession.conversation.id,
      projectId: activeSession.config.projectId,
      planVersionId: previewedPlanVersion.id,
      expectedPlanVersion: previewedPlanVersion.version,
      permissionProfile,
      message: buildExecutionPrompt(),
      messageId: `desktop-build-${approvalId}`,
      idempotencyKey: `desktop-plan-approval-${approvalId}`,
      environmentKind,
    });
  };

  const approveAndStart = async () => {
    if (!session || !planApproval || !approvalReady) return;
    const operationEpoch = flowEpochRef.current;
    setPhase('launching');
    setFlowError(null);
    try {
      if (planApproval.kind === 'versioned_atomic') {
        const previewedPlanVersion = planVersion ?? planApproval.plan_version;
        if (!previewedPlanVersion) throw new Error(t('task.planApprovalUnavailable'));
        const result = await approveVersionedPlan(session, previewedPlanVersion);
        if (flowEpochRef.current !== operationEpoch) return;
        onSessionReady({ ...session, conversation: result.conversation });
      } else {
        if (!(await approveLegacyPlan(session, operationEpoch))) {
          if (flowEpochRef.current !== operationEpoch) return;
          setPhase('review');
          return;
        }
        if (flowEpochRef.current !== operationEpoch) return;
        onSessionReady(session);
      }
      closeFlow();
    } catch (error) {
      if (flowEpochRef.current !== operationEpoch) return;
      const message = error instanceof Error ? error.message : String(error);
      setFlowError(message);
      setPhase('review');
      onError(message);
    }
  };

  const changeKind = (nextKind: NewTaskKind) => {
    setKind(nextKind);
    setEnvironmentKind(nextKind === 'programming' ? 'worktree' : 'local');
    setPermissionProfile(defaultPermissionProfile(nextKind));
  };

  const addReviewStep = () => {
    const id = `human-step-${crypto.randomUUID()}`;
    setReviewSteps((current) => [
      ...current,
      { id, sourceTaskId: null, content: '', priority: 'medium', enabled: true },
    ]);
    return id;
  };

  return createPortal(
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <div className="new-task-backdrop">
        <section
          ref={dialogRef}
          className="new-task-window"
          role="dialog"
          aria-modal="true"
          aria-labelledby="new-task-title"
        >
          <header className="new-task-header">
            <div className="new-task-brand">
              <img src="/icon-192.png" alt="" />
              <span>
                <strong id="new-task-title">{t('task.createTask')}</strong>
                <small>{t('task.createSubtitle')}</small>
              </span>
            </div>
            <ol className="new-task-steps" aria-label={t('task.progress')}>
              <FlowStep
                index={1}
                label={t('task.describeTask')}
                active={phase === 'define'}
                done={phase !== 'define'}
              />
              <FlowStep
                index={2}
                label={t('task.agentPlan')}
                active={phase === 'planning'}
                done={phase === 'review' || phase === 'launching'}
              />
              <FlowStep
                index={3}
                label={t('task.reviewPlan')}
                active={phase === 'review' || phase === 'launching'}
                done={phase === 'launching'}
              />
            </ol>
            <button className="new-task-close" type="button" aria-label={t('task.close')} onClick={closeFlow}>
              <Cross2Icon />
            </button>
          </header>

          <main className="new-task-content">
            {phase === 'define' ? (
              <NewTaskDefinitionStage
                title={title}
                objective={objective}
                kind={kind}
                contextSources={contextSources}
                workspaceRoot={workspaceRoot}
                workspaceSelection={workspaceSelection}
                newWorkspaceValue={NEW_WORKSPACE_VALUE}
                workspaces={workspaces}
                environmentKind={environmentKind}
                titleInputRef={titleInputRef}
                onTitleChange={setTitle}
                onObjectiveChange={setObjective}
                onKindChange={changeKind}
                onContextSourcesChange={setContextSources}
                onWorkspaceRootChange={setWorkspaceRoot}
                onWorkspaceSelectionChange={setWorkspaceSelection}
                onEnvironmentKindChange={setEnvironmentKind}
              />
            ) : null}
            {phase === 'planning' ? (
              <NewTaskPlanningStage
                title={title}
                objective={objective}
                kind={kind}
                workspaceLabel={workspaceLabel}
                contextCount={contextSources.length}
                retryAvailable={planRetryAvailable}
                onRetry={() => void retryPlanning()}
              />
            ) : null}
            {phase === 'review' || phase === 'launching' ? (
              <NewTaskReviewStage
                title={title}
                objective={objective}
                kind={kind}
                planVersion={planVersion}
                approval={planApproval}
                planRequiresReview={planRequiresReview}
                revisionAwaitingPlan={revisionAwaitingPlan}
                manualPlanReviewRequired={manualPlanReviewRequired}
                reviewSteps={reviewSteps}
                contextSources={contextSources}
                environmentKind={environmentKind}
                permissionProfile={permissionProfile}
                revisionFeedback={revisionFeedback}
                revisionComposerOpen={revisionComposerOpen}
                launching={phase === 'launching'}
                onAcknowledgeVersion={() => setPlanRequiresReview(false)}
                onStopWaitingForRevision={stopWaitingForRevision}
                onAcknowledgeCurrentPlan={() => setManualPlanReviewRequired(false)}
                onReviewStepsChange={setReviewSteps}
                onAddStep={addReviewStep}
                onPermissionProfileChange={setPermissionProfile}
                onRevisionFeedbackChange={setRevisionFeedback}
                onRequestRevision={() => void requestRevision()}
              />
            ) : null}
            {flowError ? (
              <div className="new-task-error" role="alert">
                {flowError}
              </div>
            ) : null}
          </main>

          <footer className="new-task-footer">
            {phase === 'define' ? (
              <>
                <span>
                  <MagicWandIcon /> {disabledReason ?? t('task.generatePlanHint')}
                </span>
                <button
                  className="primary"
                  type="button"
                  disabled={!canGenerate}
                  onClick={() => void generatePlan()}
                >
                  {t('task.generatePlan')} <ArrowRightIcon />
                </button>
              </>
            ) : phase === 'planning' ? (
              <>
                <span>{t('task.waitingForPlan')}</span>
                <button type="button" onClick={closeFlow}>
                  {t('task.continueBackground')}
                </button>
              </>
            ) : (
              <>
                <div className="new-task-review-footer-summary">
                  <NewTaskFooterBackButton onClick={() => setPhase('define')} />
                  <span>{t('task.selectedSteps', { selected: enabledStepCount, total: reviewSteps.length })}</span>
                </div>
                <div className="new-task-review-footer-actions">
                  {reviewDirty ? (
                    <button
                      type="button"
                      disabled={enabledStepCount < 1 || phase === 'launching'}
                      onClick={() =>
                        void requestRevision(
                          buildPlanReplacementPrompt(reviewSteps),
                          t('task.planEditsSubmitted', { count: enabledStepCount }),
                        )
                      }
                    >
                      {t('task.applyPlanEdits')}
                    </button>
                  ) : (
                    <button
                      type="button"
                      disabled={phase === 'launching'}
                      onClick={() => setRevisionComposerOpen((current) => !current)}
                    >
                      {t('task.askAgentRevise')}
                    </button>
                  )}
                  <button
                    className="primary"
                    type="button"
                    disabled={!approvalReady || phase === 'launching'}
                    onClick={() => void approveAndStart()}
                  >
                    {phase === 'launching' ? t('task.startingBuild') : t('task.approveStart')}
                    <ArrowRightIcon />
                  </button>
                </div>
              </>
            )}
          </footer>
        </section>
      </div>
    </Theme>,
    document.body,
  );
}
