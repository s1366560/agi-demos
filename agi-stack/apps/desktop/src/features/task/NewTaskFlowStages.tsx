import { useEffect, useState } from 'react';
import {
  CheckCircledIcon,
  CodeIcon,
  DesktopIcon,
  EnterFullScreenIcon,
  FileTextIcon,
  LightningBoltIcon,
  LockClosedIcon,
  MagicWandIcon,
  MixerHorizontalIcon,
  Pencil2Icon,
  PlusIcon,
  ReaderIcon,
  ReloadIcon,
  SewingPinIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  AgentPlanApprovalCapability,
  DesktopExecutionEnvironmentKind,
  DesktopPermissionProfile,
  DesktopPlanVersion,
  WorkspaceSummary,
} from '../../types';
import {
  enabledReviewPlanSteps,
  planPriorityTranslationKey,
  type NewTaskContextSource,
  type NewTaskKind,
  type ReviewPlanStep,
} from './newTaskPlanModel';
import {
  EnvironmentButton,
  handleRadioArrowKey,
  ModeCard,
  PlanningCheck,
  StageHeading,
} from './NewTaskStagePrimitives';

const contextOptions: Array<{
  value: NewTaskContextSource;
  labelKey: string;
  descriptionKey: string;
  icon: typeof ReaderIcon;
}> = [
  {
    value: 'project_memory',
    labelKey: 'task.contextProjectMemory',
    descriptionKey: 'task.contextProjectMemoryDescription',
    icon: ReaderIcon,
  },
  {
    value: 'project_files',
    labelKey: 'task.contextProjectFiles',
    descriptionKey: 'task.contextProjectFilesDescription',
    icon: FileTextIcon,
  },
  {
    value: 'web_research',
    labelKey: 'task.contextWebResearch',
    descriptionKey: 'task.contextWebResearchDescription',
    icon: SewingPinIcon,
  },
];

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

type DefinitionStageProps = {
  title: string;
  objective: string;
  kind: NewTaskKind;
  contextSources: NewTaskContextSource[];
  workspaceRoot: string;
  workspaceSelection: string;
  newWorkspaceValue: string;
  workspaces: WorkspaceSummary[];
  environmentKind: DesktopExecutionEnvironmentKind;
  titleInputRef: React.RefObject<HTMLInputElement | null>;
  onTitleChange: (value: string) => void;
  onObjectiveChange: (value: string) => void;
  onKindChange: (value: NewTaskKind) => void;
  onContextSourcesChange: (value: NewTaskContextSource[]) => void;
  onWorkspaceRootChange: (value: string) => void;
  onWorkspaceSelectionChange: (value: string) => void;
  onEnvironmentKindChange: (value: DesktopExecutionEnvironmentKind) => void;
};

export function NewTaskDefinitionStage({
  title,
  objective,
  kind,
  contextSources,
  workspaceRoot,
  workspaceSelection,
  newWorkspaceValue,
  workspaces,
  environmentKind,
  titleInputRef,
  onTitleChange,
  onObjectiveChange,
  onKindChange,
  onContextSourcesChange,
  onWorkspaceRootChange,
  onWorkspaceSelectionChange,
  onEnvironmentKindChange,
}: DefinitionStageProps) {
  const { t } = useI18n();
  const toggleContext = (value: NewTaskContextSource) => {
    onContextSourcesChange(
      contextSources.includes(value)
        ? contextSources.filter((source) => source !== value)
        : [...contextSources, value],
    );
  };

  return (
    <div className="new-task-define">
      <section className="new-task-primary-column">
        <StageHeading
          eyebrow={t('task.eyebrow')}
          title={t('task.defineTitle')}
          description={t('task.defineDescription')}
        />
        <label className="new-task-field">
          <span>{t('task.titleLabel')}</span>
          <input
            ref={titleInputRef}
            value={title}
            maxLength={120}
            placeholder={t('task.titlePlaceholder')}
            onChange={(event) => onTitleChange(event.target.value)}
          />
        </label>
        <label className="new-task-field new-task-objective-field">
          <span>{t('task.objectiveLabel')}</span>
          <textarea
            value={objective}
            rows={7}
            placeholder={t('task.objectivePlaceholder')}
            onChange={(event) => onObjectiveChange(event.target.value)}
          />
          <small>{t('task.objectiveHelp')}</small>
        </label>
        <fieldset className="new-task-mode-field">
          <legend>{t('task.kind')}</legend>
          <div className="new-task-mode-grid" role="radiogroup">
            <ModeCard
              selected={kind === 'general'}
              icon={<MixerHorizontalIcon />}
              title={t('task.generalAgent')}
              description={t('task.generalAgentDescription')}
              onSelect={() => onKindChange('general')}
            />
            <ModeCard
              selected={kind === 'programming'}
              icon={<CodeIcon />}
              title={t('task.codeAgent')}
              description={t('task.codeAgentDescription')}
              onSelect={() => onKindChange('programming')}
            />
          </div>
        </fieldset>
      </section>

      <aside className="new-task-context-column">
        <StageHeading
          compact
          eyebrow={t('task.contextBoundaries')}
          title={t('task.contextTitle')}
        />
        <label className="new-task-field">
          <span>{t('task.workspace')}</span>
          <select
            value={workspaceSelection}
            onChange={(event) => onWorkspaceSelectionChange(event.target.value)}
          >
            <option value={newWorkspaceValue}>{t('task.createWorkspace')}</option>
            {workspaces.map((workspace) => (
              <option key={workspace.id} value={workspace.id}>
                {workspace.name || workspace.title || workspace.id}
              </option>
            ))}
          </select>
        </label>
        <fieldset className="new-task-context-field">
          <legend>{t('task.availableContext')}</legend>
          <div className="new-task-context-options">
            {contextOptions.map((option) => {
              const Icon = option.icon;
              const selected = contextSources.includes(option.value);
              return (
                <button
                  type="button"
                  className={selected ? 'selected' : ''}
                  aria-pressed={selected}
                  key={option.value}
                  onClick={() => toggleContext(option.value)}
                >
                  <Icon />
                  <span>
                    <strong>{t(option.labelKey)}</strong>
                    <small>{t(option.descriptionKey)}</small>
                  </span>
                  {selected ? <CheckCircledIcon /> : <i aria-hidden />}
                </button>
              );
            })}
          </div>
        </fieldset>
        {kind === 'programming' ? (
          <div className="new-task-code-boundary">
            <label className="new-task-field">
              <span>{t('task.codeRoot')}</span>
              <input
                value={workspaceRoot}
                placeholder="/workspace/repository"
                onChange={(event) => onWorkspaceRootChange(event.target.value)}
              />
            </label>
            <fieldset className="new-task-environment-field">
              <legend>{t('task.environment')}</legend>
              <div role="radiogroup">
                <EnvironmentButton
                  selected={environmentKind === 'worktree'}
                  icon={<EnterFullScreenIcon />}
                  title={t('task.isolatedWorktree')}
                  description={t('task.isolatedWorktreeDescription')}
                  onSelect={() => onEnvironmentKindChange('worktree')}
                />
                <EnvironmentButton
                  selected={environmentKind === 'local'}
                  icon={<DesktopIcon />}
                  title={t('task.currentWorkspace')}
                  description={t('task.currentWorkspaceDescription')}
                  onSelect={() => onEnvironmentKindChange('local')}
                />
              </div>
            </fieldset>
          </div>
        ) : null}
        <div className="new-task-protection-note">
          <LockClosedIcon />
          <span>
            <strong>{t('task.planFirstTitle')}</strong>
            <small>{t('task.authorityNote')}</small>
          </span>
        </div>
      </aside>
    </div>
  );
}

type PlanningStageProps = {
  title: string;
  objective: string;
  kind: NewTaskKind;
  workspaceLabel: string;
  contextCount: number;
  retryAvailable: boolean;
  onRetry: () => void;
};

export function NewTaskPlanningStage({
  title,
  objective,
  kind,
  workspaceLabel,
  contextCount,
  retryAvailable,
  onRetry,
}: PlanningStageProps) {
  const { t } = useI18n();
  return (
    <div className="new-task-planning">
      <section className="new-task-planning-main" aria-live="polite">
        <span className="new-task-planning-icon" aria-hidden>
          <MagicWandIcon />
        </span>
        <span className="new-task-eyebrow">{t('task.agentPlanning')}</span>
        <h2>{t('task.planningFor', { title })}</h2>
        <p>{t('task.planningSafety')}</p>
        <div className="new-task-planning-progress" aria-label={t('task.waitingForPlan')}>
          <i />
        </div>
        <div className="new-task-planning-checks">
          <PlanningCheck
            state="complete"
            title={t('task.planningOutcomeTitle')}
            description={t('task.planningOutcomeDescription')}
          />
          <PlanningCheck
            state="complete"
            title={t('task.planningContextTitle')}
            description={t('task.planningContextDescription', { count: contextCount })}
          />
          <PlanningCheck
            state="active"
            title={t('task.planningPathTitle')}
            description={t('task.planningPathDescription')}
          />
          <PlanningCheck
            state="pending"
            title={t('task.planningPacketTitle')}
            description={t('task.planningPacketDescription')}
          />
        </div>
        {retryAvailable ? (
          <div className="new-task-planning-delay" role="status">
            <span>
              <strong>{t('task.planDelayedTitle')}</strong>
              <small>{t('task.planDelayedDescription')}</small>
            </span>
            <button type="button" onClick={onRetry}>
              <ReloadIcon /> {t('task.retryPlan')}
            </button>
          </div>
        ) : null}
      </section>
      <aside className="new-task-brief-card">
        <span className="new-task-eyebrow">{t('task.taskBrief')}</span>
        <h3>{title}</h3>
        <p>{objective}</p>
        <dl>
          <div>
            <dt>{t('task.mode')}</dt>
            <dd>{kind === 'programming' ? t('session.code') : t('session.work')}</dd>
          </div>
          <div>
            <dt>{t('task.workspace')}</dt>
            <dd>{workspaceLabel}</dd>
          </div>
          <div>
            <dt>{t('task.authority')}</dt>
            <dd>{t('task.planOnly')}</dd>
          </div>
        </dl>
      </aside>
    </div>
  );
}

type ReviewStageProps = {
  title: string;
  objective: string;
  kind: NewTaskKind;
  planVersion: DesktopPlanVersion | null;
  approval: AgentPlanApprovalCapability | null;
  planRequiresReview: boolean;
  revisionAwaitingPlan: boolean;
  manualPlanReviewRequired: boolean;
  reviewSteps: ReviewPlanStep[];
  contextSources: NewTaskContextSource[];
  environmentKind: DesktopExecutionEnvironmentKind;
  permissionProfile: DesktopPermissionProfile;
  revisionFeedback: string;
  revisionComposerOpen: boolean;
  launching: boolean;
  onAcknowledgeVersion: () => void;
  onStopWaitingForRevision: () => void;
  onAcknowledgeCurrentPlan: () => void;
  onReviewStepsChange: (steps: ReviewPlanStep[]) => void;
  onAddStep: () => string;
  onPermissionProfileChange: (profile: DesktopPermissionProfile) => void;
  onRevisionFeedbackChange: (value: string) => void;
  onRequestRevision: () => void;
};

export function NewTaskReviewStage({
  title,
  objective,
  kind,
  planVersion,
  approval,
  planRequiresReview,
  revisionAwaitingPlan,
  manualPlanReviewRequired,
  reviewSteps,
  contextSources,
  environmentKind,
  permissionProfile,
  revisionFeedback,
  revisionComposerOpen,
  launching,
  onAcknowledgeVersion,
  onStopWaitingForRevision,
  onAcknowledgeCurrentPlan,
  onReviewStepsChange,
  onAddStep,
  onPermissionProfileChange,
  onRevisionFeedbackChange,
  onRequestRevision,
}: ReviewStageProps) {
  const { t } = useI18n();
  const [editingId, setEditingId] = useState<string | null>(null);

  useEffect(() => {
    if (!reviewSteps.some((step) => step.id === editingId)) setEditingId(null);
  }, [editingId, reviewSteps]);

  const enabledCount = enabledReviewPlanSteps(reviewSteps).length;
  const isVersioned = approval?.kind === 'versioned_atomic';
  return (
    <div className="new-task-review">
      <section className="new-task-plan-column">
        <div className="new-task-review-heading">
          <StageHeading
            eyebrow={t('task.reviewEyebrow')}
            title={t('task.reviewTitle')}
            description={t('task.reviewDescription')}
          />
          <span className="new-task-plan-ready">
            <CheckCircledIcon /> {t('task.planReady')}
          </span>
        </div>
        <div className="new-task-plan-objective">
          <span className={kind === 'programming' ? 'code' : 'work'}>
            {kind === 'programming' ? <CodeIcon /> : <MixerHorizontalIcon />}
          </span>
          <div>
            <small>{kind === 'programming' ? t('task.codeTask') : t('task.workTask')}</small>
            <strong>{title}</strong>
            <p>{objective}</p>
          </div>
        </div>
        {planRequiresReview ? (
          <div className="new-task-plan-refresh" role="alert">
            <ReloadIcon />
            <span>
              <strong>{t(planVersion ? 'task.planUpdatedTitle' : 'task.planChangedTitle')}</strong>
              <small>
                {planVersion
                  ? t('task.planUpdatedDescription', { version: planVersion.version })
                  : t('task.planChangedDescription')}
              </small>
            </span>
            <button type="button" onClick={onAcknowledgeVersion}>
              {planVersion
                ? t('task.reviewLatestVersion', { version: planVersion.version })
                : t('task.reviewLatestPlan')}
            </button>
          </div>
        ) : null}
        {revisionAwaitingPlan ? (
          <div className="new-task-plan-refresh" role="alert">
            <ReloadIcon />
            <span>
              <strong>{t('task.revisionNotAcknowledgedTitle')}</strong>
              <small>{t('task.revisionNotAcknowledgedDescription')}</small>
            </span>
            <button type="button" onClick={onStopWaitingForRevision}>
              {t('task.stopWaitingForRevision')}
            </button>
          </div>
        ) : null}
        {manualPlanReviewRequired ? (
          <div className="new-task-plan-refresh" role="alert">
            <ReloadIcon />
            <span>
              <strong>{t('task.reviewCurrentPlanTitle')}</strong>
              <small>{t('task.reviewCurrentPlanDescription')}</small>
            </span>
            <button type="button" onClick={onAcknowledgeCurrentPlan}>
              {t('task.reviewCurrentPlanAction')}
            </button>
          </div>
        ) : null}
        <div className="new-task-review-list">
          {reviewSteps.map((step, index) => (
            <ReviewPlanStepRow
              key={step.id}
              step={step}
              index={index}
              editing={editingId === step.id}
              disabled={launching}
              onEdit={() => setEditingId(step.id)}
              onCancel={() => setEditingId(null)}
              onChange={(nextStep) =>
                onReviewStepsChange(
                  reviewSteps.map((candidate) =>
                    candidate.id === nextStep.id ? nextStep : candidate,
                  ),
                )
              }
              onSave={(nextStep) => {
                onReviewStepsChange(
                  reviewSteps.map((candidate) =>
                    candidate.id === nextStep.id ? nextStep : candidate,
                  ),
                );
                setEditingId(null);
              }}
            />
          ))}
          <button
            className="new-task-add-step"
            type="button"
            disabled={launching}
            onClick={() => setEditingId(onAddStep())}
          >
            <PlusIcon /> {t('task.addStep')}
          </button>
        </div>
      </section>

      <aside className="new-task-run-preview">
        <span className="new-task-eyebrow">{t('task.runPreview')}</span>
        <div className="new-task-preview-stats">
          <div>
            <small>{t('task.estimatedTime')}</small>
            <strong>{t('task.notProvided')}</strong>
          </div>
          <div>
            <small>{t('task.estimatedUsage')}</small>
            <strong>{t('task.notProvided')}</strong>
          </div>
        </div>
        <section>
          <h3>{t('task.executionBoundaries')}</h3>
          <ul className="new-task-boundary-list">
            <li>
              {isVersioned ? <CheckCircledIcon /> : <LockClosedIcon />}
              {isVersioned
                ? environmentKind === 'worktree'
                  ? t('task.isolatedWorktree')
                  : t('task.currentWorkspace')
                : t('task.executionEnvironmentUnavailable')}
            </li>
            <li>
              <CheckCircledIcon />
              {isVersioned
                ? t('task.atomicApprovalBoundary')
                : t('task.legacyApprovalBoundary')}
            </li>
            <li>
              <CheckCircledIcon />
              {t('task.selectedStepBoundary', { count: enabledCount })}
            </li>
          </ul>
        </section>
        <section>
          <h3>{t('task.contextAgentUse')}</h3>
          <div className="new-task-context-chips">
            {contextSources.map((source) => (
              <span key={source}>
                <ReaderIcon /> {t(contextOptions.find((option) => option.value === source)?.labelKey ?? source)}
              </span>
            ))}
          </div>
        </section>
        {isVersioned ? (
          <fieldset className="new-task-permission-profile">
            <legend>{t('task.permissionProfile')}</legend>
            <div role="radiogroup">
              {permissionProfiles.map((profile) => (
                <button
                  key={profile.value}
                  type="button"
                  role="radio"
                  aria-checked={permissionProfile === profile.value}
                  className={permissionProfile === profile.value ? 'selected' : ''}
                  disabled={launching}
                  onKeyDown={handleRadioArrowKey}
                  onClick={() => onPermissionProfileChange(profile.value)}
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
        ) : (
          <div className="new-task-legacy-note">
            <LockClosedIcon />
            <span>
              <strong>{t('task.legacyApprovalTitle')}</strong>
              <small>{t('task.legacyApprovalDescription')}</small>
            </span>
          </div>
        )}
        <div className="new-task-limited-authority">
          <LockClosedIcon />
          <span>
            <strong>
              {t(isVersioned ? 'task.limitedAuthorityTitle' : 'task.legacyAuthorityTitle')}
            </strong>
            <small>
              {isVersioned
                ? t('task.limitedAuthorityDescription', { count: enabledCount })
                : t('task.legacyAuthorityDescription')}
            </small>
          </span>
        </div>
        {revisionComposerOpen ? (
          <div className="new-task-revision-composer">
            <label>
              <span>{t('task.requestChanges')}</span>
              <textarea
                rows={4}
                value={revisionFeedback}
                disabled={launching}
                placeholder={t('task.revisionPlaceholder')}
                onChange={(event) => onRevisionFeedbackChange(event.target.value)}
              />
            </label>
            <button
              type="button"
              disabled={!revisionFeedback.trim() || launching}
              onClick={onRequestRevision}
            >
              <LightningBoltIcon /> {t('task.revisePlan')}
            </button>
          </div>
        ) : null}
      </aside>
    </div>
  );
}

function ReviewPlanStepRow({
  step,
  index,
  editing,
  disabled,
  onEdit,
  onCancel,
  onChange,
  onSave,
}: {
  step: ReviewPlanStep;
  index: number;
  editing: boolean;
  disabled: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onChange: (step: ReviewPlanStep) => void;
  onSave: (step: ReviewPlanStep) => void;
}) {
  const { t } = useI18n();
  const [content, setContent] = useState(step.content);
  const [priority, setPriority] = useState(step.priority);

  useEffect(() => {
    setContent(step.content);
    setPriority(step.priority);
  }, [editing, step.content, step.priority]);

  if (editing) {
    return (
      <article className="new-task-plan-step editing">
        <span className="new-task-step-index">{String(index + 1).padStart(2, '0')}</span>
        <div className="new-task-step-editor">
          <label>
            <span>{t('task.stepInstruction')}</span>
            <textarea
              rows={3}
              value={content}
              autoFocus
              onChange={(event) => setContent(event.target.value)}
            />
          </label>
          <label>
            <span>{t('task.priority')}</span>
            <select value={priority} onChange={(event) => setPriority(event.target.value)}>
              <option value="high">{t('task.priorityHigh')}</option>
              <option value="medium">{t('task.priorityMedium')}</option>
              <option value="low">{t('task.priorityLow')}</option>
            </select>
          </label>
          <div>
            <button type="button" onClick={onCancel}>
              {t('settings.cancel')}
            </button>
            <button
              type="button"
              className="primary"
              disabled={!content.trim()}
              onClick={() => onSave({ ...step, content: content.trim(), priority })}
            >
              {t('task.saveStep')}
            </button>
          </div>
        </div>
      </article>
    );
  }

  return (
    <article className={`new-task-plan-step ${step.enabled ? '' : 'disabled'}`}>
      <button
        className="new-task-step-toggle"
        type="button"
        disabled={disabled}
        aria-label={t(step.enabled ? 'task.disableStep' : 'task.enableStep', {
          step: step.content,
        })}
        onClick={() => onChange({ ...step, enabled: !step.enabled })}
      >
        {step.enabled ? <CheckCircledIcon /> : <span aria-hidden />}
      </button>
      <span className="new-task-step-index">{String(index + 1).padStart(2, '0')}</span>
      <div className="new-task-step-copy">
        <strong>{step.content}</strong>
        <small>
          {t('task.priorityStatus', {
            priority: t(planPriorityTranslationKey(step.priority)),
            status: t('task.reviewed'),
          })}
        </small>
        <span>
          <FileTextIcon /> {t('task.expectedOutput')}: {t('task.notProvided')}
        </span>
      </div>
      <time>{t('task.notProvided')}</time>
      <button
        className="new-task-step-edit"
        type="button"
        disabled={disabled}
        aria-label={t('task.editStep', { step: step.content })}
        onClick={onEdit}
      >
        <Pencil2Icon />
      </button>
    </article>
  );
}
