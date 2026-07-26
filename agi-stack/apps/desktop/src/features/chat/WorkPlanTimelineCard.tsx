import { useId } from 'react';
import {
  ActivityLogIcon,
  ChevronDownIcon,
  ChevronRightIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { AgentTimelineItem } from '../../types';
import { formatTimelineTime } from './chatTimelinePresentation';
import { MarkdownContent } from './ChatTranscript';
import { workPlanTimelinePresentation } from './workPlanTimelineModel';

type WorkPlanTimelineCardProps = {
  item: AgentTimelineItem;
  expanded: boolean;
  onToggle: () => void;
};

export function WorkPlanTimelineCard({
  item,
  expanded,
  onToggle,
}: WorkPlanTimelineCardProps) {
  const { t } = useI18n();
  const contentId = useId();
  const labelId = useId();
  const plan = workPlanTimelinePresentation(item);
  if (!plan) return null;

  const time = formatTimelineTime(item);
  const statusKey = workPlanStatusKey(plan.status);
  const progress =
    plan.currentStep && plan.currentStep <= plan.totalSteps
      ? t('chat.stepsProgress', {
          current: plan.currentStep,
          total: plan.totalSteps,
        })
      : t('chat.stepsCount', { count: plan.totalSteps });

  return (
    <article
      className="work-plan-timeline-card"
      data-timeline-anchor-id={item.id}
      tabIndex={-1}
    >
      <span className="work-plan-timeline-icon" aria-hidden="true">
        <ActivityLogIcon />
      </span>
      <div className="work-plan-timeline-surface">
        <button
          type="button"
          className="work-plan-timeline-toggle"
          aria-label={t(expanded ? 'chat.collapseItem' : 'chat.expandItem', {
            item: t('chat.workPlan'),
          })}
          aria-expanded={expanded}
          aria-controls={contentId}
          onClick={onToggle}
        >
          {expanded ? <ChevronDownIcon /> : <ChevronRightIcon />}
          <span id={labelId} className="work-plan-timeline-title">
            {t('chat.workPlan')}
          </span>
          <span className="work-plan-timeline-count">{progress}</span>
          {statusKey ? (
            <span className="work-plan-timeline-status">{t(statusKey)}</span>
          ) : null}
          {time ? <time className="work-plan-timeline-time">{time}</time> : null}
        </button>
        <div
          id={contentId}
          role="region"
          aria-labelledby={labelId}
          className="work-plan-timeline-content"
          hidden={!expanded}
        >
          <ol className="work-plan-timeline-steps">
            {plan.steps.map((step) => {
              const current = plan.currentStep === step.stepNumber;
              return (
                <li
                  key={step.stepNumber}
                  className={`work-plan-timeline-step${current ? ' is-current' : ''}`}
                  aria-current={current ? 'step' : undefined}
                >
                  <span className="work-plan-timeline-step-number" aria-hidden="true">
                    {step.stepNumber}
                  </span>
                  <div className="work-plan-timeline-step-body">
                    <MarkdownContent
                      content={step.description}
                      className="work-plan-timeline-step-description"
                    />
                    {step.expectedOutput ? (
                      <div className="work-plan-timeline-expected-output">
                        <span>{t('task.expectedOutput')}</span>
                        <MarkdownContent
                          content={step.expectedOutput}
                          className="work-plan-timeline-expected-output-body"
                        />
                      </div>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </article>
  );
}

function workPlanStatusKey(status: string | null): string | null {
  switch (status?.toLowerCase()) {
    case 'pending':
      return 'session.planTaskState.pending';
    case 'running':
    case 'in_progress':
      return 'session.statusRunning';
    case 'complete':
    case 'completed':
      return 'session.statusCompleted';
    case 'failed':
    case 'error':
      return 'session.statusFailed';
    default:
      return null;
  }
}
