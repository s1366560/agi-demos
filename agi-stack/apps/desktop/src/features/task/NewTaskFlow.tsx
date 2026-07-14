import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Button, Text, Theme } from '@radix-ui/themes';
import {
  CheckCircledIcon,
  CodeIcon,
  Cross2Icon,
  DesktopIcon,
  EnterFullScreenIcon,
  FileTextIcon,
  LightningBoltIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { DesktopApiClient } from '../../api/client';
import { useI18n } from '../../i18n';
import type {
  AgentConversation,
  AgentPlanTask,
  DesktopExecutionEnvironmentKind,
  DesktopPermissionProfile,
  DesktopPlanVersion,
  DesktopRuntimeConfig,
  WorkspaceSummary,
} from '../../types';
import {
  buildExecutionPrompt,
  buildPlanningPrompt,
  buildRevisionPrompt,
  orderedPlanTasks,
  planTaskSignature,
  type NewTaskDefinition,
  type NewTaskKind,
} from './newTaskPlanModel';
import './NewTaskFlow.css';

type NewTaskFlowPhase = 'define' | 'planning' | 'review' | 'launching';

export type NewTaskSession = {
  workspace: WorkspaceSummary;
  conversation: AgentConversation;
  config: DesktopRuntimeConfig;
};

type NewTaskFlowProps = {
  open: boolean;
  config: DesktopRuntimeConfig;
  workspaces: WorkspaceSummary[];
  preferredWorkspaceId?: string;
  disabledReason?: string | null;
  onClose: () => void;
  onSessionReady: (session: NewTaskSession) => void;
  onError: (message: string) => void;
};

const NEW_WORKSPACE_VALUE = '__new_workspace__';
const PLAN_POLL_INTERVAL_MS = 1_500;
const permissionProfiles: Array<{
  value: DesktopPermissionProfile;
  labelKey: string;
  descriptionKey: string;
}> = [
  {
    value: 'read_only',
    labelKey: 'task.permissionReadOnly',
    descriptionKey: 'task.permissionReadOnlyDescription',
  },
  {
    value: 'workspace_write',
    labelKey: 'task.permissionWorkspaceWrite',
    descriptionKey: 'task.permissionWorkspaceWriteDescription',
  },
  {
    value: 'full_access',
    labelKey: 'task.permissionFullAccess',
    descriptionKey: 'task.permissionFullAccessDescription',
  },
];

export function planVersionIdentity(planVersion: DesktopPlanVersion | null | undefined): string {
  return planVersion ? `${planVersion.id}:${planVersion.version}` : '';
}

export function hasPlanVersionChanged(
  current: DesktopPlanVersion | null | undefined,
  next: DesktopPlanVersion | null | undefined,
): boolean {
  const nextIdentity = planVersionIdentity(next);
  return Boolean(nextIdentity) && nextIdentity !== planVersionIdentity(current);
}

export function canApprovePlanVersion(
  planVersion: DesktopPlanVersion | null | undefined,
  requiresReview: boolean,
): boolean {
  return Boolean(
    planVersion?.id &&
      planVersion.version > 0 &&
      planVersion.status === 'draft' &&
      !requiresReview,
  );
}

export function defaultPermissionProfile(kind: NewTaskKind): DesktopPermissionProfile {
  return kind === 'programming' ? 'workspace_write' : 'read_only';
}

export function NewTaskFlow({
  open,
  config,
  workspaces,
  preferredWorkspaceId,
  disabledReason,
  onClose,
  onSessionReady,
  onError,
}: NewTaskFlowProps) {
  const { t } = useI18n();
  const [phase, setPhase] = useState<NewTaskFlowPhase>('define');
  const [title, setTitle] = useState('');
  const [objective, setObjective] = useState('');
  const [kind, setKind] = useState<NewTaskKind>('general');
  const [environmentKind, setEnvironmentKind] =
    useState<DesktopExecutionEnvironmentKind>('local');
  const [permissionProfile, setPermissionProfile] =
    useState<DesktopPermissionProfile>('read_only');
  const [workspaceRoot, setWorkspaceRoot] = useState(config.workspaceRoot);
  const [workspaceSelection, setWorkspaceSelection] = useState(
    preferredWorkspaceId || config.workspaceId || NEW_WORKSPACE_VALUE,
  );
  const [planTasks, setPlanTasks] = useState<AgentPlanTask[]>([]);
  const [planVersion, setPlanVersion] = useState<DesktopPlanVersion | null>(null);
  const [planRequiresReview, setPlanRequiresReview] = useState(false);
  const [revisionFeedback, setRevisionFeedback] = useState('');
  const [flowError, setFlowError] = useState<string | null>(null);
  const [session, setSession] = useState<NewTaskSession | null>(null);
  const expectedPlanSignatureRef = useRef('');
  const displayedPlanSignatureRef = useRef('');
  const displayedPlanVersionRef = useRef<DesktopPlanVersion | null>(null);
  const approvalAttemptRef = useRef<{ identity: string; id: string } | null>(null);
  const titleInputRef = useRef<HTMLInputElement>(null);

  const selectedWorkspace = useMemo(
    () => workspaces.find((workspace) => workspace.id === workspaceSelection) ?? null,
    [workspaceSelection, workspaces],
  );
  const orderedTasks = useMemo(() => orderedPlanTasks(planTasks), [planTasks]);
  const approvalReady = canApprovePlanVersion(planVersion, planRequiresReview);
  const canGenerate =
    title.trim().length > 0 &&
    objective.trim().length > 0 &&
    Boolean(config.projectId.trim()) &&
    !disabledReason;

  useEffect(() => {
    if (!open) return;
    setPhase('define');
    setTitle('');
    setObjective('');
    setKind('general');
    setEnvironmentKind('local');
    setPermissionProfile('read_only');
    setWorkspaceRoot(config.workspaceRoot);
    setWorkspaceSelection(preferredWorkspaceId || config.workspaceId || NEW_WORKSPACE_VALUE);
    setPlanTasks([]);
    setPlanVersion(null);
    setPlanRequiresReview(false);
    setRevisionFeedback('');
    setFlowError(null);
    setSession(null);
    expectedPlanSignatureRef.current = '';
    displayedPlanSignatureRef.current = '';
    displayedPlanVersionRef.current = null;
    approvalAttemptRef.current = null;
    window.setTimeout(() => titleInputRef.current?.focus(), 0);
  }, [config.workspaceId, config.workspaceRoot, open, preferredWorkspaceId]);

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
        const nextPlanVersion = response.plan_version ?? null;
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

        if (tasks.length > 0 && (isNewPlanningResult || isNewReviewResult)) {
          const requiresAnotherReview = phase === 'review';
          displayedPlanSignatureRef.current = signature;
          displayedPlanVersionRef.current = nextPlanVersion;
          setPlanTasks(tasks);
          setPlanVersion(nextPlanVersion);
          setPlanRequiresReview(requiresAnotherReview);
          setFlowError(null);
          setPhase('review');
        }
        scheduleNextPoll();
      } catch (error) {
        if (stopped || abortController.signal.aborted) return;
        setFlowError(error instanceof Error ? error.message : String(error));
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

  const generatePlan = async () => {
    if (!canGenerate) return;
    setPhase('planning');
    setFlowError(null);
    const definition: NewTaskDefinition = { title, objective, kind, workspaceRoot };
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
      await client.runAgentMessage(
        conversation.id,
        buildPlanningPrompt(definition),
        `desktop-plan-${crypto.randomUUID()}`,
        config.projectId,
      );
      const readySession = { workspace, conversation, config: scopedConfig };
      setSession(readySession);
      onSessionReady(readySession);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setFlowError(message);
      setPhase('define');
      onError(message);
    }
  };

  const requestRevision = async () => {
    const feedback = revisionFeedback.trim();
    if (!session || !feedback) return;
    expectedPlanSignatureRef.current = planTaskSignature(planTasks);
    setPlanRequiresReview(false);
    setRevisionFeedback('');
    setFlowError(null);
    setPhase('planning');
    try {
      const client = new DesktopApiClient(session.config);
      await client.sendMessage(feedback);
      await client.runAgentMessage(
        session.conversation.id,
        buildRevisionPrompt(feedback),
        `desktop-plan-revision-${crypto.randomUUID()}`,
        session.config.projectId,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setFlowError(message);
      setPhase('review');
      onError(message);
    }
  };

  const approveAndStart = async () => {
    const previewedPlanVersion = planVersion;
    if (
      !session ||
      planTasks.length === 0 ||
      !previewedPlanVersion ||
      !canApprovePlanVersion(previewedPlanVersion, planRequiresReview)
    ) {
      return;
    }
    setPhase('launching');
    setFlowError(null);
    try {
      const client = new DesktopApiClient(session.config);
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
      const result = await client.approvePlanAndStart({
        conversationId: session.conversation.id,
        projectId: session.config.projectId,
        planVersionId: previewedPlanVersion.id,
        expectedPlanVersion: previewedPlanVersion.version,
        permissionProfile,
        message: buildExecutionPrompt(),
        messageId: `desktop-build-${approvalId}`,
        idempotencyKey: `desktop-plan-approval-${approvalId}`,
        environmentKind,
      });
      onSessionReady({
        ...session,
        conversation: result.conversation,
      });
      onClose();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setFlowError(message);
      setPhase('review');
      onError(message);
    }
  };

  return createPortal(
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <div className="new-task-backdrop">
        <section
          className="new-task-window"
          role="dialog"
          aria-modal="true"
          aria-labelledby="new-task-title"
        >
          <header className="new-task-header">
            <div>
              <Text size="1" color="gray">
                {t('task.eyebrow')}
              </Text>
              <h1 id="new-task-title">{t('task.createTitle')}</h1>
            </div>
            <button type="button" aria-label={t('task.close')} onClick={onClose}>
              <Cross2Icon />
            </button>
          </header>

          <ol className="new-task-steps" aria-label={t('task.progress')}>
            <FlowStep
              index={1}
              label={t('task.define')}
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
              label={t('task.humanReview')}
              active={phase === 'review' || phase === 'launching'}
              done={phase === 'launching'}
            />
          </ol>

        <div className="new-task-content">
          {phase === 'define' ? (
            <div className="new-task-define">
              <section className="new-task-main-form">
                <label>
                  <span>{t('task.titleLabel')}</span>
                  <input
                    ref={titleInputRef}
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                    placeholder={t('task.titlePlaceholder')}
                    maxLength={120}
                  />
                </label>
                <label>
                  <span>{t('task.objectiveLabel')}</span>
                  <textarea
                    value={objective}
                    onChange={(event) => setObjective(event.target.value)}
                    placeholder={t('task.objectivePlaceholder')}
                    rows={9}
                  />
                </label>
              </section>

              <aside className="new-task-context-card">
                <div className="new-task-kind" role="radiogroup" aria-label={t('task.kind')}>
                  <button
                    type="button"
                    role="radio"
                    aria-checked={kind === 'general'}
                    className={kind === 'general' ? 'selected' : ''}
                    onClick={() => {
                      setKind('general');
                      setEnvironmentKind('local');
                      setPermissionProfile(defaultPermissionProfile('general'));
                    }}
                  >
                    <FileTextIcon />
                    <span>{t('task.generalAgent')}</span>
                    <small>{t('task.generalAgentDescription')}</small>
                  </button>
                  <button
                    type="button"
                    role="radio"
                    aria-checked={kind === 'programming'}
                    className={kind === 'programming' ? 'selected' : ''}
                    onClick={() => {
                      setKind('programming');
                      setEnvironmentKind('worktree');
                      setPermissionProfile(defaultPermissionProfile('programming'));
                    }}
                  >
                    <CodeIcon />
                    <span>{t('task.codeAgent')}</span>
                    <small>{t('task.codeAgentDescription')}</small>
                  </button>
                </div>

                <label>
                  <span>{t('task.workspace')}</span>
                  <select
                    value={workspaceSelection}
                    onChange={(event) => setWorkspaceSelection(event.target.value)}
                  >
                    <option value={NEW_WORKSPACE_VALUE}>{t('task.createWorkspace')}</option>
                    {workspaces.map((workspace) => (
                      <option key={workspace.id} value={workspace.id}>
                        {workspace.name || workspace.title || workspace.id}
                      </option>
                    ))}
                  </select>
                </label>

                {kind === 'programming' ? (
                  <>
                    <label>
                      <span>{t('task.codeRoot')}</span>
                      <input
                        value={workspaceRoot}
                        onChange={(event) => setWorkspaceRoot(event.target.value)}
                        placeholder="/workspace/repository"
                      />
                    </label>
                    <div>
                      <span className="new-task-field-label">{t('task.environment')}</span>
                      <div
                        className="new-task-environment"
                        role="radiogroup"
                        aria-label={t('task.environment')}
                      >
                        <button
                          type="button"
                          role="radio"
                          aria-checked={environmentKind === 'worktree'}
                          className={environmentKind === 'worktree' ? 'selected' : ''}
                          onClick={() => setEnvironmentKind('worktree')}
                        >
                          <EnterFullScreenIcon />
                          <span>
                            <strong>{t('task.isolatedWorktree')}</strong>
                            <small>{t('task.isolatedWorktreeDescription')}</small>
                          </span>
                        </button>
                        <button
                          type="button"
                          role="radio"
                          aria-checked={environmentKind === 'local'}
                          className={environmentKind === 'local' ? 'selected' : ''}
                          onClick={() => setEnvironmentKind('local')}
                        >
                          <DesktopIcon />
                          <span>
                            <strong>{t('task.currentWorkspace')}</strong>
                            <small>{t('task.currentWorkspaceDescription')}</small>
                          </span>
                        </button>
                      </div>
                    </div>
                  </>
                ) : null}

                <div className="new-task-authority-note">
                  <CheckCircledIcon />
                  <span>{t('task.authorityNote')}</span>
                </div>
              </aside>
            </div>
          ) : null}

          {phase === 'planning' ? (
            <div className="new-task-planning" aria-live="polite">
              <span className="new-task-orbit" aria-hidden>
                <LightningBoltIcon />
              </span>
              <Text size="1" color="gray">
                {t('task.planReadOnly')}
              </Text>
              <h2>{t('task.planningTitle')}</h2>
              <p>{t('task.planningDescription')}</p>
              <div className="new-task-planning-status">
                <ReloadIcon /> {t('task.waitingForPlan')}
              </div>
            </div>
          ) : null}

          {phase === 'review' || phase === 'launching' ? (
            <div className="new-task-review">
              <section className="new-task-plan-card">
                <div className="new-task-plan-heading">
                  <div>
                    <Text size="1" color="gray">
                      {t('task.planVersion')}
                    </Text>
                    <h2>{title}</h2>
                    <div className="new-task-plan-identity">
                      <span>
                        <small>{t('task.planId')}</small>
                        <code title={planVersion?.id}>
                          {planVersion?.id ?? t('task.planIdentityPending')}
                        </code>
                      </span>
                      <span>
                        <small>{t('task.version')}</small>
                        <strong>{planVersion ? `v${planVersion.version}` : '—'}</strong>
                      </span>
                    </div>
                  </div>
                  <span>{t('task.stepCount', { count: orderedTasks.length })}</span>
                </div>
                {planRequiresReview && planVersion ? (
                  <div className="new-task-plan-refresh-notice" role="alert">
                    <ReloadIcon />
                    <span>
                      <strong>{t('task.planUpdatedTitle')}</strong>
                      <small>
                        {t('task.planUpdatedDescription', { version: planVersion.version })}
                      </small>
                    </span>
                    <button type="button" onClick={() => setPlanRequiresReview(false)}>
                      {t('task.reviewLatestVersion', { version: planVersion.version })}
                    </button>
                  </div>
                ) : null}
                {!planVersion ? (
                  <div className="new-task-plan-refresh-notice pending" role="status">
                    <ReloadIcon />
                    <span>
                      <strong>{t('task.planIdentityPending')}</strong>
                      <small>{t('task.planApprovalUnavailable')}</small>
                    </span>
                  </div>
                ) : null}
                <ol className="new-task-plan-list">
                  {orderedTasks.map((task, index) => (
                    <li key={task.id}>
                      <span>{String(index + 1).padStart(2, '0')}</span>
                      <div>
                        <strong>{task.content}</strong>
                        <small>
                          {t('task.priorityStatus', {
                            priority: task.priority || 'medium',
                            status: task.status || 'pending',
                          })}
                        </small>
                      </div>
                    </li>
                  ))}
                </ol>
              </section>

              <aside className="new-task-review-actions">
                <div className="new-task-run-preview-heading">
                  <Text size="1" color="gray">
                    {t('task.runPreview')}
                  </Text>
                  <strong>{t('task.runPreviewDescription')}</strong>
                </div>
                <div className="new-task-launch-context">
                  {environmentKind === 'worktree' ? <EnterFullScreenIcon /> : <DesktopIcon />}
                  <span>
                    <strong>
                      {environmentKind === 'worktree'
                        ? t('task.isolatedWorktree')
                        : t('task.currentWorkspace')}
                    </strong>
                    <small>{t('task.environmentCreatedAfterApproval')}</small>
                  </span>
                </div>
                <div className="new-task-authority-note">
                  <CheckCircledIcon />
                  <span>{t('task.notAuthorized')}</span>
                </div>
                <fieldset className="new-task-permission-profile">
                  <legend>{t('task.permissionProfile')}</legend>
                  <div role="radiogroup" aria-label={t('task.permissionProfile')}>
                    {permissionProfiles.map((profile) => (
                      <button
                        key={profile.value}
                        type="button"
                        role="radio"
                        aria-checked={permissionProfile === profile.value}
                        className={permissionProfile === profile.value ? 'selected' : ''}
                        disabled={phase === 'launching'}
                        onClick={() => setPermissionProfile(profile.value)}
                      >
                        <span>
                          <strong>{t(profile.labelKey)}</strong>
                          <small>{t(profile.descriptionKey)}</small>
                        </span>
                        <i aria-hidden />
                      </button>
                    ))}
                  </div>
                </fieldset>
                <div className="new-task-plan-approval-binding">
                  <CheckCircledIcon />
                  <span>
                    {planVersion
                      ? t('task.approvalBindsPlan', {
                          planId: planVersion.id,
                          version: planVersion.version,
                        })
                      : t('task.planApprovalUnavailable')}
                  </span>
                </div>
                <label>
                  <span>{t('task.requestChanges')}</span>
                  <textarea
                    rows={5}
                    value={revisionFeedback}
                    onChange={(event) => setRevisionFeedback(event.target.value)}
                    placeholder={t('task.revisionPlaceholder')}
                    disabled={phase === 'launching'}
                  />
                </label>
                <Button
                  size="3"
                  variant="soft"
                  disabled={!revisionFeedback.trim() || phase === 'launching'}
                  onClick={() => void requestRevision()}
                >
                  {t('task.revisePlan')}
                </Button>
                <Button
                  size="3"
                  disabled={phase === 'launching' || !approvalReady}
                  onClick={() => void approveAndStart()}
                >
                  <LightningBoltIcon />
                  {phase === 'launching'
                    ? t('task.startingBuild')
                    : planVersion
                      ? t('task.approveStartVersion', { version: planVersion.version })
                      : t('task.approveStart')}
                </Button>
              </aside>
            </div>
          ) : null}

          {flowError ? <div className="new-task-error">{flowError}</div> : null}
        </div>

        <footer className="new-task-footer">
          <Text size="1" color="gray">
            {disabledReason ?? t('task.authorityTransition')}
          </Text>
          {phase === 'define' ? (
            <Button size="3" disabled={!canGenerate} onClick={() => void generatePlan()}>
              {t('task.generatePlan')}
            </Button>
          ) : (
            <Button variant="ghost" onClick={onClose}>
              {t('task.continueBackground')}
            </Button>
          )}
        </footer>
        </section>
      </div>
    </Theme>,
    document.body,
  );
}

function FlowStep({
  index,
  label,
  active,
  done,
}: {
  index: number;
  label: string;
  active: boolean;
  done: boolean;
}) {
  return (
    <li className={active ? 'active' : done ? 'done' : ''} aria-current={active ? 'step' : undefined}>
      <span>{done ? <CheckCircledIcon /> : index}</span>
      {label}
    </li>
  );
}
