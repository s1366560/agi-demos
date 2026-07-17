import { useEffect, useState } from 'react';
import { Badge, Button } from '@radix-ui/themes';
import { CheckCircledIcon, RocketIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  DesktopExecutionEnvironmentKind,
  DesktopPermissionProfile,
} from '../../types';
import {
  canApproveSessionPlan,
  defaultSessionPlanApprovalSelection,
  sessionPlanTaskPriorityTranslationKey,
  sessionPlanTaskStatusTranslationKey,
  type SessionPlanApprovalSelection,
} from './sessionPlanApprovalModel';
import type {
  SessionProjectionCapabilities,
  SessionProjectionPlan,
  SessionProjectionTask,
} from './sessionProjectionTypes';
import type { SessionCapabilityMode } from './sessionViewModel';

type SessionPlanReviewProps = {
  plan: SessionProjectionPlan;
  capabilities: SessionProjectionCapabilities | null;
  capabilityMode: SessionCapabilityMode;
  pending: boolean;
  onApprove: (
    plan: SessionProjectionPlan,
    selection: SessionPlanApprovalSelection,
  ) => Promise<void>;
};

type SessionTaskListReviewProps = {
  tasks: SessionProjectionTask[];
  canResumeReview?: boolean;
  onResumeReview: () => void;
};

export function SessionPlanReview({
  plan,
  capabilities,
  capabilityMode,
  pending,
  onApprove,
}: SessionPlanReviewProps) {
  const { t } = useI18n();
  const [selection, setSelection] = useState<SessionPlanApprovalSelection>(() =>
    defaultSessionPlanApprovalSelection(capabilityMode),
  );
  const canApprove = canApproveSessionPlan(plan, capabilities);

  useEffect(() => {
    setSelection(defaultSessionPlanApprovalSelection(capabilityMode));
  }, [capabilityMode, plan.id, plan.version]);

  return (
    <>
      <header className="session-plan-review-header">
        <span>{t('session.planReviewKicker')}</span>
        <div>
          <h2>{t('session.planVersion', { version: plan.version })}</h2>
          <Badge color={plan.status === 'draft' ? 'amber' : 'green'} variant="soft">
            {t(`session.planStatus.${plan.status}`)}
          </Badge>
        </div>
        <p>{t('session.planReviewDescription')}</p>
      </header>

      <ol
        className="session-plan-task-list"
        aria-label={t('session.planTaskList', { count: plan.tasks.length })}
      >
        {plan.tasks.map((task, index) => (
          <PlanTaskRow key={task.id} task={task} index={index} />
        ))}
      </ol>

      {plan.status === 'draft' ? (
        <section
          className="session-plan-approval-card"
          aria-label={t('session.planApprovalTitle')}
          aria-busy={pending}
        >
          <header>
            <span>
              <RocketIcon aria-hidden="true" />
            </span>
            <div>
              <strong>{t('session.planApprovalTitle')}</strong>
              <small>{t('session.planApprovalDescription', { version: plan.version })}</small>
            </div>
          </header>
          <div className="session-plan-approval-fields">
            <label>
              <span>{t('session.planEnvironment')}</span>
              <select
                value={selection.environmentKind}
                disabled={pending}
                onChange={(event) => {
                  const environmentKind = event.currentTarget
                    .value as DesktopExecutionEnvironmentKind;
                  setSelection((current) => ({
                    ...current,
                    environmentKind,
                  }));
                }}
              >
                <option value="local">{t('task.currentWorkspace')}</option>
                <option value="worktree">{t('task.isolatedWorktree')}</option>
              </select>
            </label>
            <label>
              <span>{t('task.permissionProfile')}</span>
              <select
                value={selection.permissionProfile}
                disabled={pending}
                onChange={(event) => {
                  const permissionProfile = event.currentTarget.value as DesktopPermissionProfile;
                  setSelection((current) => ({
                    ...current,
                    permissionProfile,
                  }));
                }}
              >
                <option value="read_only">{t('task.permissionReadOnly')}</option>
                <option value="workspace_write">{t('task.permissionWorkspaceWrite')}</option>
                <option value="full_access">{t('task.permissionFullAccess')}</option>
              </select>
            </label>
          </div>
          <Button
            type="button"
            size="2"
            disabled={!canApprove || pending}
            onClick={() => void onApprove(plan, selection)}
          >
            <RocketIcon aria-hidden="true" />
            <span aria-live="polite" aria-atomic="true">
              {pending
                ? t('session.planApprovalStarting')
                : t('session.planApproveAndStart', { version: plan.version })}
            </span>
          </Button>
          <small className="session-plan-approval-authority">
            {canApprove
              ? t('session.planApprovalAuthorityReady')
              : t('session.planApprovalAuthorityUnavailable')}
          </small>
        </section>
      ) : (
        <div className="session-plan-approved-note" role="status">
          <CheckCircledIcon aria-hidden="true" />
          <span>
            <strong>{t('session.planApprovedTitle')}</strong>
            <small>{t('session.planApprovedDescription')}</small>
          </span>
        </div>
      )}
    </>
  );
}

export function SessionTaskListReview({
  tasks,
  canResumeReview = true,
  onResumeReview,
}: SessionTaskListReviewProps) {
  const { t } = useI18n();
  return (
    <>
      <header className="session-plan-review-header">
        <span>{t('session.taskListReviewKicker')}</span>
        <div>
          <h2>{t('session.taskListReviewTitle')}</h2>
          <Badge color="amber" variant="soft">
            {t('session.taskListReviewBadge')}
          </Badge>
        </div>
        <p>{t('session.taskListReviewDescription')}</p>
      </header>
      <ol
        className="session-plan-task-list"
        aria-label={t('session.planTaskList', { count: tasks.length })}
      >
        {tasks.map((task, index) => (
          <PlanTaskRow key={task.id} task={task} index={index} />
        ))}
      </ol>
      <section className="session-plan-approval-card" aria-label={t('session.taskListResumeTitle')}>
        <header>
          <span>
            <RocketIcon aria-hidden="true" />
          </span>
          <div>
            <strong>{t('session.taskListResumeTitle')}</strong>
            <small>
              {canResumeReview
                ? t('session.taskListResumeAuthority')
                : t('session.taskListResumeUnavailable')}
            </small>
          </div>
        </header>
        <Button
          type="button"
          size="2"
          disabled={!canResumeReview}
          onClick={onResumeReview}
        >
          {t('session.taskListResumeAction')}
        </Button>
      </section>
    </>
  );
}

function PlanTaskRow({ task, index }: { task: SessionProjectionTask; index: number }) {
  const { t } = useI18n();
  const content =
    (typeof task.content === 'string' && task.content.trim()) ||
    (typeof task.title === 'string' && task.title.trim()) ||
    t('session.planStepFallback', { index: index + 1 });
  const rawStatus =
    typeof task.status === 'string' && task.status.trim()
      ? task.status
      : 'pending';
  const status = t(sessionPlanTaskStatusTranslationKey(rawStatus));
  const rawPriority =
    (typeof task.priority === 'string' || typeof task.priority === 'number') &&
    String(task.priority).trim()
      ? String(task.priority)
      : null;
  const priority = rawPriority
    ? t(sessionPlanTaskPriorityTranslationKey(rawPriority))
    : null;

  return (
    <li>
      <span className="session-plan-task-index" aria-hidden="true">
        {index + 1}
      </span>
      <span>
        <strong>{content}</strong>
        <small>
          {priority
            ? t('session.planTaskStatusWithPriority', { status, priority })
            : t('session.planTaskStatus', { status })}
        </small>
      </span>
      {rawStatus === 'completed' ? <CheckCircledIcon aria-hidden="true" /> : null}
    </li>
  );
}
