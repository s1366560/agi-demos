import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Theme } from '@radix-ui/themes';
import {
  ArrowRightIcon,
  Cross2Icon,
  MagicWandIcon,
} from '@radix-ui/react-icons';

import {
  DesktopApiClient,
  isTaskSessionIdempotencyConflictError,
} from '../../api/client';
import { useI18n } from '../../i18n';
import type {
  AgentConversation,
  AgentInputFileMetadata,
  AgentPlanApprovalCapability,
  AgentPlanTask,
  DesktopExecutionEnvironmentKind,
  DesktopPermissionProfile,
  DesktopPlanVersion,
  DesktopRuntimeConfig,
  WorkspaceAuthorityCollection,
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
  browserLegacyPlanApprovalStorage,
  canActivateNewTaskSession,
  clearLegacyPlanApprovalRecovery,
  createLegacyPlanApprovalRecovery,
  createReviewPlanDraft,
  enabledReviewPlanSteps,
  hasReviewPlanChanges,
  isFreshPlanningPlan,
  legacyPlanApprovalRuntimeScope,
  newTaskDefinitionSignature,
  orderedPlanTasks,
  planTaskSignature,
  planningTurnAttempt,
  readLegacyPlanApprovalRecovery,
  shouldOfferPlanRetry,
  writeLegacyPlanApprovalRecovery,
  type NewTaskAgentTurnOutcome,
  type NewTaskContextSource,
  type NewTaskDefinition,
  type NewTaskKind,
  type PlanningTurnAttempt,
  type ReviewPlanStep,
} from './newTaskPlanModel';
import {
  browserTaskSessionCreationStorage,
  buildLocalTaskSessionRequest,
  canUseNewTaskWorkspaceSelection,
  clearTaskSessionCreationAttempt,
  NEW_WORKSPACE_VALUE,
  newTaskWorkspaceLabel,
  readTaskSessionCreationAttempt,
  resolveTaskSessionConflictWorkspace,
  taskSessionCreationAttempt,
  taskSessionCreationFingerprint,
  writeTaskSessionCreationAttempt,
  type TaskSessionCreationAttempt,
} from './newTaskSessionModel';
import {
  NewTaskDefinitionStage,
  NewTaskPlanningStage,
  NewTaskReviewStage,
} from './NewTaskFlowStages';
import { FlowStep, NewTaskFooterBackButton } from './NewTaskStagePrimitives';
import './NewTaskFlow.css';
import './NewTaskPlanReview.css';

type NewTaskFlowPhase = 'define' | 'planning' | 'review' | 'launching';

type TaskSessionConflictRecovery = {
  fingerprint: string;
  workspaceSelection: string;
  existingWorkspace: WorkspaceSummary | null;
};

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
  agentId?: string;
  forcedSkillName?: string;
  mentions?: string[];
  fileMetadata?: AgentInputFileMetadata[];
  appModelContext?: Record<string, unknown>;
};

export type NewTaskResumeDraft = {
  session: NewTaskSession;
  definition: NewTaskDefinition;
  tasks: AgentPlanTask[];
};

type NewTaskFlowProps = {
  open: boolean;
  config: DesktopRuntimeConfig;
  actorId: string | null | undefined;
  workspaceAuthority?: WorkspaceAuthorityCollection<WorkspaceSummary>;
  workspaces?: WorkspaceSummary[];
  resumeDraft?: NewTaskResumeDraft | null;
  preferredWorkspaceId?: string;
  preferredKind?: NewTaskKind;
  disabledReason?: string | null;
  onClose: () => void;
  onSessionPersisted: (session: NewTaskSession) => void;
  onSessionReady: (session: NewTaskSession) => void;
  onRunAgentTurn: (input: NewTaskAgentTurnInput) => Promise<NewTaskAgentTurnOutcome>;
  onOpenRuntimeSettings: () => void;
  onError: (message: string | null) => void;
};

const PLAN_POLL_INTERVAL_MS = 1_500;
const DEFAULT_CONTEXT_SOURCES: NewTaskContextSource[] = [
  'project_memory',
  'project_files',
];

export function NewTaskFlow({
  open,
  config,
  actorId,
  workspaceAuthority,
  workspaces,
  resumeDraft = null,
  preferredWorkspaceId,
  preferredKind,
  disabledReason,
  onClose,
  onSessionPersisted,
  onSessionReady,
  onRunAgentTurn,
  onOpenRuntimeSettings,
  onError,
}: NewTaskFlowProps) {
  const { t } = useI18n();
  const normalizedActorId = actorId?.trim() ?? '';
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
  const [taskSessionConflictRecovery, setTaskSessionConflictRecovery] =
    useState<TaskSessionConflictRecovery | null>(null);
  const [runtimeRecoveryAvailable, setRuntimeRecoveryAvailable] = useState(false);
  const [deliveryOutcomeUnknown, setDeliveryOutcomeUnknown] = useState(false);
  const [session, setSession] = useState<NewTaskSession | null>(null);
  const expectedPlanSignatureRef = useRef('');
  const displayedPlanSignatureRef = useRef('');
  const displayedPlanVersionRef = useRef<DesktopPlanVersion | null>(null);
  const lastPlanningPromptRef = useRef('');
  const planningAttemptRef = useRef<PlanningTurnAttempt | null>(null);
  const planningConversationIdRef = useRef('');
  const sessionDefinitionSignatureRef = useRef('');
  const sessionWorkspaceSelectionRef = useRef('');
  const emptyPlanPollCountRef = useRef(0);
  const flowEpochRef = useRef(0);
  const phaseRef = useRef(phase);
  const keyboardNavigationRef = useRef(false);
  const preserveSubmittedWorkRef = useRef(false);
  const generatePlanPendingRef = useRef(false);
  const taskSessionCreationAttemptRef = useRef<TaskSessionCreationAttempt | null>(null);
  const activeActorIdRef = useRef(normalizedActorId);
  const modalActorIdRef = useRef(normalizedActorId);
  const wasOpenRef = useRef(false);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const onCloseRef = useRef(onClose);
  const approvalAttemptRef = useRef<{ identity: string; messageId: string } | null>(null);
  const legacyBuildRecoveryRef = useRef(false);
  const titleInputRef = useRef<HTMLInputElement>(null);
  const reviewHeadingRef = useRef<HTMLHeadingElement>(null);
  phaseRef.current = phase;
  onCloseRef.current = onClose;
  activeActorIdRef.current = normalizedActorId;

  const resolvedWorkspaceAuthority = workspaceAuthority ?? {
    status: workspaces ? ('ready' as const) : ('unavailable' as const),
    items: workspaces ?? [],
    error: null,
  };
  const selectedWorkspace = useMemo(
    () =>
      resolvedWorkspaceAuthority.items.find(
        (workspace) => workspace.id === workspaceSelection,
      ) ?? null,
    [resolvedWorkspaceAuthority.items, workspaceSelection],
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
  const workspaceAuthorityDisabledReason =
    resolvedWorkspaceAuthority.status === 'loading' ||
    resolvedWorkspaceAuthority.status === 'unavailable'
      ? t('task.workspaceAuthorityLoading')
      : resolvedWorkspaceAuthority.status === 'error'
        ? t('task.workspaceAuthorityError')
        : workspaceSelection !== NEW_WORKSPACE_VALUE && !selectedWorkspace
          ? t('task.workspaceSelectionStale')
          : null;
  const effectiveDisabledReason = disabledReason ?? workspaceAuthorityDisabledReason;
  const canGenerate =
    title.trim().length > 0 &&
    objective.trim().length > 0 &&
    contextSources.length > 0 &&
    Boolean(config.projectId.trim()) &&
    canUseNewTaskWorkspaceSelection(resolvedWorkspaceAuthority, workspaceSelection) &&
    !effectiveDisabledReason;
  const currentTaskSessionFingerprint = useMemo(
    () =>
      taskSessionCreationFingerprint(
        config,
        normalizedActorId,
        { title, objective, kind, workspaceRoot, contextSources },
        workspaceSelection,
      ),
    [
      config.apiBaseUrl,
      config.mode,
      config.projectId,
      config.tenantId,
      contextSources,
      kind,
      normalizedActorId,
      objective,
      title,
      workspaceRoot,
      workspaceSelection,
    ],
  );
  const taskSessionConflictIsCurrent =
    taskSessionConflictRecovery?.fingerprint === currentTaskSessionFingerprint;
  const taskSessionConflictWorkspace =
    taskSessionConflictIsCurrent &&
    taskSessionConflictRecovery?.workspaceSelection === NEW_WORKSPACE_VALUE
      ? taskSessionConflictRecovery.existingWorkspace
      : null;
  const taskSessionConflictActionAvailable =
    taskSessionConflictIsCurrent &&
    taskSessionConflictRecovery !== null &&
    (taskSessionConflictRecovery.workspaceSelection !== NEW_WORKSPACE_VALUE ||
      taskSessionConflictWorkspace !== null);
  const workspaceLabel = newTaskWorkspaceLabel(
    session?.workspace ?? null,
    selectedWorkspace,
    workspaceSelection,
    t('task.createWorkspace'),
  );

  useEffect(() => {
    if (wasOpenRef.current === open) return;
    wasOpenRef.current = open;
    if (!open && preserveSubmittedWorkRef.current) {
      preserveSubmittedWorkRef.current = false;
      return;
    }
    flowEpochRef.current += 1;
    if (!open) return;
    preserveSubmittedWorkRef.current = false;
    const recoveredDefinition = resumeDraft?.definition ?? null;
    const recoveredTasks = resumeDraft ? orderedPlanTasks(resumeDraft.tasks) : [];
    const nextKind = recoveredDefinition?.kind ?? preferredKind ?? 'general';
    const nextWorkspaceSelection =
      resumeDraft?.session.workspace.id ||
      preferredWorkspaceId ||
      config.workspaceId ||
      NEW_WORKSPACE_VALUE;
    const recoveredSignature = recoveredDefinition
      ? newTaskDefinitionSignature(recoveredDefinition, nextWorkspaceSelection)
      : '';
    const recoveredPlanSignature = planTaskSignature(recoveredTasks);
    setPhase(resumeDraft ? 'review' : 'define');
    setTitle(recoveredDefinition?.title ?? '');
    setObjective(recoveredDefinition?.objective ?? '');
    setKind(nextKind);
    setContextSources(recoveredDefinition?.contextSources ?? DEFAULT_CONTEXT_SOURCES);
    setEnvironmentKind(nextKind === 'programming' ? 'worktree' : 'local');
    setPermissionProfile(defaultPermissionProfile(nextKind));
    setWorkspaceRoot(recoveredDefinition?.workspaceRoot ?? config.workspaceRoot);
    setWorkspaceSelection(nextWorkspaceSelection);
    setPlanTasks(recoveredTasks);
    setReviewSteps(createReviewPlanDraft(recoveredTasks));
    setPlanVersion(null);
    setPlanApproval(resumeDraft ? { kind: 'legacy_mode_switch' } : null);
    setPlanRequiresReview(false);
    setRevisionAwaitingPlan(false);
    setManualPlanReviewRequired(false);
    setPlanRetryAvailable(false);
    setRevisionFeedback('');
    setRevisionComposerOpen(false);
    setFlowError(null);
    setTaskSessionConflictRecovery(null);
    setRuntimeRecoveryAvailable(false);
    setDeliveryOutcomeUnknown(false);
    setSession(resumeDraft?.session ?? null);
    expectedPlanSignatureRef.current = recoveredPlanSignature;
    displayedPlanSignatureRef.current = recoveredPlanSignature;
    displayedPlanVersionRef.current = null;
    lastPlanningPromptRef.current = '';
    planningAttemptRef.current = null;
    taskSessionCreationAttemptRef.current = null;
    generatePlanPendingRef.current = false;
    planningConversationIdRef.current = '';
    sessionDefinitionSignatureRef.current = recoveredSignature;
    sessionWorkspaceSelectionRef.current = resumeDraft ? nextWorkspaceSelection : '';
    emptyPlanPollCountRef.current = 0;
    const recoveredApproval = resumeDraft
      ? readLegacyPlanApprovalRecovery(
          browserLegacyPlanApprovalStorage(),
          resumeDraft.session.conversation.id,
          recoveredPlanSignature,
          legacyPlanApprovalRuntimeScope(resumeDraft.session.config),
        )
      : null;
    approvalAttemptRef.current = recoveredApproval
      ? {
          identity: [
            'legacy',
            recoveredApproval.conversationId,
            recoveredApproval.planSignature,
          ].join(':'),
          messageId: recoveredApproval.messageId,
        }
      : null;
    legacyBuildRecoveryRef.current = Boolean(
      recoveredApproval && resumeDraft?.session.conversation.current_mode === 'build',
    );
    window.setTimeout(() => {
      if (!resumeDraft) {
        titleInputRef.current?.focus();
        return;
      }
      reviewHeadingRef.current?.focus();
    }, 0);
  }, [
    config.workspaceId,
    config.workspaceRoot,
    open,
    preferredKind,
    preferredWorkspaceId,
    resumeDraft,
  ]);

  useEffect(() => {
    const previousActorId = modalActorIdRef.current;
    modalActorIdRef.current = normalizedActorId;
    if (previousActorId === normalizedActorId) return;

    flowEpochRef.current += 1;
    preserveSubmittedWorkRef.current = false;
    generatePlanPendingRef.current = false;
    taskSessionCreationAttemptRef.current = null;
    planningAttemptRef.current = null;
    planningConversationIdRef.current = '';
    sessionDefinitionSignatureRef.current = '';
    sessionWorkspaceSelectionRef.current = '';
    approvalAttemptRef.current = null;
    legacyBuildRecoveryRef.current = false;
    setSession(null);
    setPlanTasks([]);
    setReviewSteps([]);
    setPlanVersion(null);
    setPlanApproval(null);
    setTaskSessionConflictRecovery(null);
    setFlowError(null);
    setPhase('define');
    if (open) onCloseRef.current();
  }, [normalizedActorId, open]);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Tab') keyboardNavigationRef.current = true;
      if (event.key === 'Escape') {
        event.preventDefault();
        if (phaseRef.current === 'define') {
          flowEpochRef.current += 1;
        } else {
          preserveSubmittedWorkRef.current = true;
        }
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
    const handlePointerDown = () => {
      keyboardNavigationRef.current = false;
    };
    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('pointerdown', handlePointerDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('pointerdown', handlePointerDown);
      window.setTimeout(() => previousFocusRef.current?.focus(), 0);
    };
  }, [open]);

  useEffect(() => {
    if (!open || phase !== 'review') return;
    const frame = window.requestAnimationFrame(() => {
      const heading = reviewHeadingRef.current;
      if (!heading) return;
      heading.dataset.keyboardFocus = keyboardNavigationRef.current ? 'true' : 'false';
      reviewHeadingRef.current?.focus();
    });
    return () => {
      window.cancelAnimationFrame(frame);
      reviewHeadingRef.current?.removeAttribute('data-keyboard-focus');
    };
  }, [open, phase]);

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
      if (
        phase === 'planning' &&
        session.conversation.id !== planningConversationIdRef.current
      ) {
        scheduleNextPoll();
        return;
      }
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
          isFreshPlanningPlan(
            tasks,
            signature,
            expectedPlanSignatureRef.current,
            versionChanged,
          );
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
          setDeliveryOutcomeUnknown(false);
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
    if (phase === 'define') {
      flowEpochRef.current += 1;
    } else {
      preserveSubmittedWorkRef.current = true;
    }
    onClose();
  };

  const openRuntimeSettings = () => {
    flowEpochRef.current += 1;
    previousFocusRef.current = null;
    onOpenRuntimeSettings();
  };

  const runAgentTurn = async (
    targetSession: NewTaskSession,
    message: string,
    messageId: string,
  ): Promise<NewTaskAgentTurnOutcome> =>
    onRunAgentTurn({
      config: targetSession.config,
      conversationId: targetSession.conversation.id,
      projectId: targetSession.config.projectId,
      message,
      messageId,
    });

  const planningMessageId = (
    targetSession: NewTaskSession,
    prompt: string,
    prefix: string,
  ): string => {
    const fingerprint = [
      targetSession.conversation.id,
      expectedPlanSignatureRef.current,
      prompt,
    ].join(':');
    const attempt = planningTurnAttempt(
      planningAttemptRef.current,
      fingerprint,
      () => `${prefix}-${crypto.randomUUID()}`,
    );
    planningAttemptRef.current = attempt;
    return attempt.messageId;
  };

  const generatePlan = async (workspaceSelectionOverride?: string) => {
    if (!canGenerate || generatePlanPendingRef.current) return;
    generatePlanPendingRef.current = true;
    const operationEpoch = flowEpochRef.current;
    const operationActorId = normalizedActorId;
    const targetWorkspaceSelection =
      workspaceSelectionOverride ?? workspaceSelection;
    let rejectedCreationFingerprint: string | null = null;
    setPhase('planning');
    setFlowError(null);
    setRuntimeRecoveryAvailable(false);
    setDeliveryOutcomeUnknown(false);
    onError(null);
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
    const planningIntentChanged = lastPlanningPromptRef.current !== planningPrompt;
    const definitionSignature = newTaskDefinitionSignature(
      definition,
      targetWorkspaceSelection,
    );
    lastPlanningPromptRef.current = planningPrompt;
    try {
      const sessionMatchesDefinition = Boolean(
        session &&
          session.conversation.user_id === operationActorId &&
          sessionDefinitionSignatureRef.current === definitionSignature &&
          sessionWorkspaceSelectionRef.current === targetWorkspaceSelection,
      );
      planningConversationIdRef.current = sessionMatchesDefinition
        ? (session?.conversation.id ?? '')
        : '';
      if (sessionMatchesDefinition && planTasks.length > 0 && !planningIntentChanged) {
        setPhase('review');
        return;
      }
      let readySession = sessionMatchesDefinition ? session : null;
      if (!readySession) {
        const baseClient = new DesktopApiClient(config);
        if (config.mode === 'cloud') {
          try {
            if (!(await baseClient.supportsAgentPlanWorkflow())) {
              throw new Error(t('task.planRuntimeUnsupported'));
            }
            if (
              flowEpochRef.current !== operationEpoch ||
              activeActorIdRef.current !== operationActorId
            ) {
              return;
            }
          } catch (error) {
            if (
              flowEpochRef.current === operationEpoch &&
              activeActorIdRef.current === operationActorId
            ) {
              setRuntimeRecoveryAvailable(true);
            }
            throw error;
          }
        }
        const creationFingerprint = taskSessionCreationFingerprint(
          config,
          operationActorId,
          definition,
          targetWorkspaceSelection,
        );
        const creationStorage = browserTaskSessionCreationStorage();
        const storedCreationAttempt = readTaskSessionCreationAttempt(
          creationStorage,
          creationFingerprint,
        );
        const creationAttempt = taskSessionCreationAttempt(
          taskSessionCreationAttemptRef.current?.fingerprint === creationFingerprint
            ? taskSessionCreationAttemptRef.current
            : storedCreationAttempt,
          creationFingerprint,
          () => `desktop-task-session-${crypto.randomUUID()}`,
        );
        if (
          !creationFingerprint ||
          !writeTaskSessionCreationAttempt(creationStorage, creationAttempt)
        ) {
          throw new Error(t('task.creationRecoveryUnavailable'));
        }
        taskSessionCreationAttemptRef.current = creationAttempt;
        let result;
        try {
          result = await baseClient.createTaskSession(
            buildLocalTaskSessionRequest(
              definition,
              targetWorkspaceSelection,
              creationAttempt.idempotencyKey,
            ),
          );
        } catch (error) {
          if (isTaskSessionIdempotencyConflictError(error)) {
            rejectedCreationFingerprint = creationFingerprint;
          }
          throw error;
        }
        if (
          flowEpochRef.current !== operationEpoch ||
          activeActorIdRef.current !== operationActorId
        ) {
          return;
        }
        readySession = {
          workspace: result.workspace,
          conversation: result.conversation,
          config: { ...config, workspaceId: result.workspace.id },
        };
        planningConversationIdRef.current = readySession.conversation.id;
        onSessionPersisted(readySession);
        clearTaskSessionCreationAttempt(creationStorage, creationFingerprint);
        taskSessionCreationAttemptRef.current = null;
        setTaskSessionConflictRecovery(null);
        setSession(readySession);
        setWorkspaceSelection(readySession.workspace.id);
        sessionDefinitionSignatureRef.current = newTaskDefinitionSignature(
          definition,
          readySession.workspace.id,
        );
        sessionWorkspaceSelectionRef.current = readySession.workspace.id;
        displayedPlanSignatureRef.current = '';
        displayedPlanVersionRef.current = null;
        expectedPlanSignatureRef.current = '';
        setPlanTasks([]);
        setReviewSteps([]);
        setPlanVersion(null);
        setPlanApproval(null);
      }
      expectedPlanSignatureRef.current = displayedPlanSignatureRef.current;
      const outcome = await runAgentTurn(
        readySession,
        planningPrompt,
        planningMessageId(readySession, planningPrompt, 'desktop-plan'),
      );
      if (
        flowEpochRef.current !== operationEpoch ||
        activeActorIdRef.current !== operationActorId
      ) {
        return;
      }
      setDeliveryOutcomeUnknown(outcome === 'unknown_outcome');
      if (
        canActivateNewTaskSession(
          readySession.workspace.id,
          readySession.conversation.workspace_id,
          outcome,
        )
      ) {
        onSessionReady(readySession);
      }
    } catch (error) {
      if (
        flowEpochRef.current !== operationEpoch ||
        activeActorIdRef.current !== operationActorId
      ) {
        return;
      }
      const conflictFingerprint = rejectedCreationFingerprint;
      const taskSessionConflict = conflictFingerprint !== null;
      let existingConflictWorkspace: WorkspaceSummary | null = null;
      if (
        taskSessionConflict &&
        targetWorkspaceSelection === NEW_WORKSPACE_VALUE
      ) {
        try {
          const workspaces = await new DesktopApiClient(config).listWorkspaces();
          if (
            flowEpochRef.current !== operationEpoch ||
            activeActorIdRef.current !== operationActorId
          ) {
            return;
          }
          existingConflictWorkspace = resolveTaskSessionConflictWorkspace(
            workspaces,
            definition.title,
          );
        } catch {
          if (
            flowEpochRef.current !== operationEpoch ||
            activeActorIdRef.current !== operationActorId
          ) {
            return;
          }
        }
      }
      const message = taskSessionConflict
        ? targetWorkspaceSelection === NEW_WORKSPACE_VALUE
          ? existingConflictWorkspace
            ? t('task.creationWorkspaceConflictResolved', {
                workspace: existingConflictWorkspace.name ?? definition.title.trim(),
              })
            : t('task.creationWorkspaceConflictUnresolved')
          : t('task.creationIdempotencyConflict')
        : error instanceof Error
          ? error.message
          : String(error);
      if (conflictFingerprint) {
        setTaskSessionConflictRecovery({
          fingerprint: conflictFingerprint,
          workspaceSelection: targetWorkspaceSelection,
          existingWorkspace: existingConflictWorkspace,
        });
        setRuntimeRecoveryAvailable(false);
      } else if (config.mode === 'local') {
        setRuntimeRecoveryAvailable(true);
      }
      setFlowError(message);
      setPhase('define');
      onError(message);
    } finally {
      if (
        flowEpochRef.current === operationEpoch &&
        activeActorIdRef.current === operationActorId
      ) {
        generatePlanPendingRef.current = false;
      }
    }
  };

  const createAsNewTask = async () => {
    const conflictRecovery = taskSessionConflictRecovery;
    const conflictFingerprint = conflictRecovery?.fingerprint ?? '';
    const targetWorkspaceSelection =
      conflictRecovery?.workspaceSelection === NEW_WORKSPACE_VALUE
        ? (conflictRecovery.existingWorkspace?.id ?? '')
        : (conflictRecovery?.workspaceSelection ?? '');
    const retryActorId = normalizedActorId;
    if (
      !canGenerate ||
      !conflictRecovery ||
      !targetWorkspaceSelection ||
      conflictFingerprint !== currentTaskSessionFingerprint ||
      !retryActorId ||
      activeActorIdRef.current !== retryActorId ||
      generatePlanPendingRef.current
    ) {
      return;
    }
    const currentAttempt = taskSessionCreationAttemptRef.current;
    if (currentAttempt && currentAttempt.fingerprint !== conflictFingerprint) {
      const message = t('task.creationConflictResetUnavailable');
      setFlowError(message);
      onError(message);
      return;
    }
    if (
      !clearTaskSessionCreationAttempt(
        browserTaskSessionCreationStorage(),
        conflictFingerprint,
      )
    ) {
      const message = t('task.creationConflictResetUnavailable');
      setFlowError(message);
      onError(message);
      return;
    }
    if (activeActorIdRef.current !== retryActorId) return;
    taskSessionCreationAttemptRef.current = null;
    setTaskSessionConflictRecovery(null);
    await generatePlan(targetWorkspaceSelection);
  };

  const requestRevision = async (agentPrompt?: string, workspaceMessage?: string) => {
    const feedback = revisionFeedback.trim();
    const prompt = agentPrompt ?? buildRevisionPrompt(feedback);
    const humanMessage = workspaceMessage ?? feedback;
    if (!session || !prompt || !humanMessage) return;
    const operationEpoch = flowEpochRef.current;
    expectedPlanSignatureRef.current = planTaskSignature(planTasks);
    planningConversationIdRef.current = session.conversation.id;
    lastPlanningPromptRef.current = prompt;
    setRevisionAwaitingPlan(true);
    setManualPlanReviewRequired(false);
    setPlanRetryAvailable(false);
    setDeliveryOutcomeUnknown(false);
    emptyPlanPollCountRef.current = 0;
    setRevisionComposerOpen(false);
    setFlowError(null);
    setPhase('planning');
    try {
      const client = new DesktopApiClient(session.config);
      await client.sendMessage(humanMessage);
      const outcome = await runAgentTurn(
        session,
        prompt,
        planningMessageId(session, prompt, 'desktop-plan-revision'),
      );
      if (flowEpochRef.current !== operationEpoch) return;
      setDeliveryOutcomeUnknown(outcome === 'unknown_outcome');
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
    planningConversationIdRef.current = session.conversation.id;
    setPlanRetryAvailable(false);
    setDeliveryOutcomeUnknown(false);
    emptyPlanPollCountRef.current = 0;
    setFlowError(null);
    try {
      const outcome = await runAgentTurn(
        session,
        prompt,
        planningMessageId(session, prompt, 'desktop-plan-retry'),
      );
      if (flowEpochRef.current !== operationEpoch) return;
      setDeliveryOutcomeUnknown(outcome === 'unknown_outcome');
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
    const recoveryStorage = browserLegacyPlanApprovalStorage();
    const recoveryScope = legacyPlanApprovalRuntimeScope(activeSession.config);
    if (!recoveryScope) {
      throw new Error(t('task.approvalRecoveryUnavailable'));
    }
    if (
      legacyBuildRecoveryRef.current &&
      !readLegacyPlanApprovalRecovery(
        recoveryStorage,
        activeSession.conversation.id,
        displayedPlanSignatureRef.current,
        recoveryScope,
      )
    ) {
      throw new Error(t('task.legacyApprovalReconcileRequired'));
    }
    if (!(await refreshLegacyPlanBeforeApproval(operationEpoch))) return false;
    if (flowEpochRef.current !== operationEpoch) return false;
    const approvalIdentity = [
      'legacy',
      activeSession.conversation.id,
      displayedPlanSignatureRef.current,
    ].join(':');
    if (approvalAttemptRef.current?.identity !== approvalIdentity) {
      const recoveredApproval = readLegacyPlanApprovalRecovery(
        recoveryStorage,
        activeSession.conversation.id,
        displayedPlanSignatureRef.current,
        recoveryScope,
      );
      approvalAttemptRef.current = {
        identity: approvalIdentity,
        messageId: recoveredApproval?.messageId ?? `desktop-build-${crypto.randomUUID()}`,
      };
    }
    const recovery = createLegacyPlanApprovalRecovery(
      activeSession.conversation.id,
      displayedPlanSignatureRef.current,
      approvalAttemptRef.current.messageId,
      recoveryScope,
    );
    if (!writeLegacyPlanApprovalRecovery(recoveryStorage, recovery)) {
      throw new Error(t('task.approvalRecoveryUnavailable'));
    }
    let switchedThisAttempt = false;
    if (!legacyBuildRecoveryRef.current) {
      await client.switchPlanMode(activeSession.conversation.id, 'build');
      legacyBuildRecoveryRef.current = true;
      switchedThisAttempt = true;
    }
    try {
      const outcome = await runAgentTurn(
        activeSession,
        buildExecutionPrompt(),
        approvalAttemptRef.current.messageId,
      );
      if (outcome === 'unknown_outcome') {
        setFlowError(t('task.agentTurnOutcomeUnknown'));
        return false;
      }
    } catch (error) {
      if (switchedThisAttempt) {
        try {
          await client.switchPlanMode(activeSession.conversation.id, 'plan');
          legacyBuildRecoveryRef.current = false;
          clearLegacyPlanApprovalRecovery(recoveryStorage, activeSession.conversation.id);
        } catch {
          throw new Error(t('task.legacyRollbackFailed'));
        }
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
      approvalAttemptRef.current = {
        identity: approvalIdentity,
        messageId: crypto.randomUUID(),
      };
    }
    const approvalId = approvalAttemptRef.current.messageId;
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

          <div
            className="new-task-visually-hidden"
            role="status"
            aria-live="polite"
            aria-atomic="true"
          >
            {phase === 'review' ? t('task.reviewReadyAnnouncement') : ''}
          </div>

          <main className="new-task-content">
            {phase === 'define' ? (
              <NewTaskDefinitionStage
                title={title}
                objective={objective}
                kind={kind}
                contextSources={contextSources}
                workspaceSelection={workspaceSelection}
                newWorkspaceValue={NEW_WORKSPACE_VALUE}
                workspaces={resolvedWorkspaceAuthority.items}
                workspaceSelectionDisabled={resolvedWorkspaceAuthority.status !== 'ready'}
                titleInputRef={titleInputRef}
                onTitleChange={setTitle}
                onObjectiveChange={setObjective}
                onKindChange={changeKind}
                onContextSourcesChange={setContextSources}
                onWorkspaceSelectionChange={setWorkspaceSelection}
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
                deliveryOutcomeUnknown={deliveryOutcomeUnknown}
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
                headingRef={reviewHeadingRef}
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
                  <MagicWandIcon /> {effectiveDisabledReason ?? t('task.generatePlanHint')}
                </span>
                <div className="new-task-review-footer-actions">
                  {runtimeRecoveryAvailable ? (
                    <button type="button" onClick={openRuntimeSettings}>
                      {t('task.openRuntimeSettings')}
                    </button>
                  ) : null}
                  {taskSessionConflictActionAvailable ? (
                    <button
                      className="primary"
                      type="button"
                      disabled={!canGenerate}
                      onClick={() => void createAsNewTask()}
                    >
                      {taskSessionConflictWorkspace
                        ? t('task.continueInWorkspace', {
                            workspace: taskSessionConflictWorkspace.name ?? title.trim(),
                          })
                        : t('task.createAsNewTask')}{' '}
                      <ArrowRightIcon />
                    </button>
                  ) : taskSessionConflictIsCurrent ? null : (
                    <button
                      className="primary"
                      type="button"
                      disabled={!canGenerate}
                      onClick={() => void generatePlan()}
                    >
                      {t('task.generatePlan')} <ArrowRightIcon />
                    </button>
                  )}
                </div>
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
                  <NewTaskFooterBackButton
                    onClick={() => {
                      expectedPlanSignatureRef.current = displayedPlanSignatureRef.current;
                      setPhase('define');
                    }}
                  />
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
