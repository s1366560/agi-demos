import {
  CheckIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CodeIcon,
  ExclamationTriangleIcon,
  StarIcon,
  UpdateIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import { formatToolCallDuration } from './chatTimelineModel';
import type {
  SkillTimelineGroup,
  SkillTimelineStatus,
  SkillToolStep,
} from './skillTimelineGroupModel';

export function SkillTimelineCard({
  skill,
  expanded,
  onToggle,
  anchorId,
}: {
  skill: SkillTimelineGroup;
  expanded: boolean;
  onToggle: () => void;
  anchorId: string;
}) {
  const { t } = useI18n();
  const name = skill.skillName || skill.skillId || t('chat.skillUnnamed');
  const progress = skillProgress(skill);
  const confidence = formatConfidence(skill.matchScore);
  const executionMode = skill.executionMode.toLowerCase();
  const modeKey = ['direct', 'prompt', 'forced'].includes(executionMode)
    ? executionMode
    : 'unknown';

  return (
    <article
      className="skill-execution-card"
      data-status={skill.status}
      data-timeline-anchor-id={anchorId}
      data-timeline-anchor-members={JSON.stringify(skill.itemIds)}
    >
      <button
        type="button"
        className="skill-execution-header"
        aria-expanded={expanded}
        aria-label={t(expanded ? 'chat.collapseItem' : 'chat.expandItem', { item: name })}
        onClick={onToggle}
      >
        <span className="skill-execution-chevron" aria-hidden="true">
          {expanded ? <ChevronDownIcon /> : <ChevronRightIcon />}
        </span>
        <span className="skill-execution-icon" aria-hidden="true">
          <SkillStatusIcon status={skill.status} />
        </span>
        <span className="skill-execution-copy">
          <strong>{t('chat.skillExecutionTitle', { name })}</strong>
          <small>
            {t('chat.skillLifecycleCount', { count: skill.itemIds.length })}
          </small>
        </span>
        <span className="skill-execution-metrics">
          {confidence ? (
            <span title={t('chat.skillMatchConfidence')}>{confidence}</span>
          ) : null}
          {skill.executionMode ? (
            <span title={t('chat.skillMode')}>{t(`chat.skillMode.${modeKey}`)}</span>
          ) : null}
          {skill.executionTimeMs !== null ? (
            <span>{formatToolCallDuration(skill.executionTimeMs)}</span>
          ) : null}
          <em className={`timeline-status ${skillStatusTone(skill.status)}`}>
            {t(`chat.skillStatus.${skill.status}`)}
          </em>
        </span>
      </button>
      {skill.status === 'matched' || skill.status === 'executing' || skill.status === 'failed' ? (
        <div
          className="skill-progress"
          role="progressbar"
          aria-label={t('chat.skillProgress')}
          aria-valuemin={0}
          aria-valuemax={skill.totalSteps || 100}
          aria-valuenow={skill.totalSteps ? skill.currentStep : progress}
          aria-valuetext={
            skill.totalSteps
              ? t('chat.skillStepProgress', {
                  current: skill.currentStep,
                  total: skill.totalSteps,
                })
              : t(`chat.skillStatus.${skill.status}`)
          }
        >
          <span className="skill-progress-bar" style={{ width: `${progress}%` }} />
        </div>
      ) : null}
      {expanded ? (
        <div className="skill-execution-body">
          <SkillTextDetail label={t('chat.skillQuery')} value={skill.query} />
          {skill.toolSteps.length ? (
            <section className="skill-tool-chain" aria-label={t('chat.skillToolChain')}>
              <div className="skill-section-heading">
                <span>{t('chat.skillToolChain')}</span>
                <small>
                  {t('chat.skillToolCount', {
                    current: completedToolCount(skill.toolSteps),
                    total: skill.toolSteps.length,
                  })}
                </small>
              </div>
              <ol>
                {skill.toolSteps.map((step) => (
                  <SkillToolStepView step={step} key={step.key} />
                ))}
              </ol>
            </section>
          ) : null}
          <SkillTextDetail
            label={t('chat.skillSummary')}
            value={skill.summary}
            tone="success"
          />
          <SkillTextDetail label={t('chat.skillError')} value={skill.error} tone="error" />
          <SkillTextDetail
            label={t('chat.skillFallbackReason')}
            value={skill.reason}
            tone="warning"
          />
        </div>
      ) : null}
    </article>
  );
}

function SkillToolStepView({ step }: { step: SkillToolStep }) {
  const { t } = useI18n();
  const input = formatEvidence(step.input);
  const output = formatEvidence(step.result);
  return (
    <li data-status={step.status}>
      <span className="skill-tool-step-index" aria-hidden="true">
        {step.status === 'running' ? (
          <UpdateIcon />
        ) : step.status === 'completed' ? (
          <CheckIcon />
        ) : step.status === 'error' ? (
          <ExclamationTriangleIcon />
        ) : (
          step.stepIndex + 1
        )}
      </span>
      <div className="skill-tool-step-copy">
        <div>
          <CodeIcon aria-hidden="true" />
          <strong>{step.toolName || t('chat.skillUnnamedTool')}</strong>
          <span>{t(`chat.skillToolStatus.${step.status}`)}</span>
          {step.durationMs !== null ? <em>{formatToolCallDuration(step.durationMs)}</em> : null}
        </div>
        {step.error ? <p className="skill-tool-step-error">{step.error}</p> : null}
        {input || output ? (
          <div className="skill-tool-evidence">
            {input ? (
              <details>
                <summary>{t('chat.skillInput')}</summary>
                <pre>{input}</pre>
              </details>
            ) : null}
            {output ? (
              <details>
                <summary>{t('chat.skillOutput')}</summary>
                <pre>{output}</pre>
              </details>
            ) : null}
          </div>
        ) : null}
      </div>
    </li>
  );
}

function SkillTextDetail({
  label,
  value,
  tone = 'default',
}: {
  label: string;
  value: string;
  tone?: 'default' | 'success' | 'error' | 'warning';
}) {
  if (!value) return null;
  return (
    <div className="skill-text-detail" data-tone={tone}>
      <span>{label}</span>
      <p>{value}</p>
    </div>
  );
}

function SkillStatusIcon({ status }: { status: SkillTimelineStatus }) {
  if (status === 'completed') return <CheckIcon />;
  if (status === 'failed' || status === 'fallback') return <ExclamationTriangleIcon />;
  if (status === 'executing') return <UpdateIcon />;
  return <StarIcon />;
}

function skillStatusTone(status: SkillTimelineStatus): 'ok' | 'error' | 'waiting' {
  if (status === 'completed') return 'ok';
  if (status === 'failed' || status === 'fallback') return 'error';
  return 'waiting';
}

function skillProgress(skill: SkillTimelineGroup): number {
  if (skill.status === 'completed' || skill.status === 'fallback') return 100;
  if (skill.totalSteps > 0) {
    return Math.min(100, Math.max(0, (skill.currentStep / skill.totalSteps) * 100));
  }
  return skill.status === 'matched' ? 0 : 50;
}

function completedToolCount(steps: readonly SkillToolStep[]): number {
  return steps.filter((step) => step.status === 'completed' || step.status === 'error').length;
}

function formatConfidence(score: number | null): string {
  if (score === null) return '';
  const percentage = score <= 1 ? score * 100 : score;
  return `${Math.round(percentage)}%`;
}

function formatEvidence(value: unknown): string {
  if (value === undefined || value === null || value === '') return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
