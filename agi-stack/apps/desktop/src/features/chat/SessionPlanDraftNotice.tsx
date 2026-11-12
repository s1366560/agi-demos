import { ActivityLogIcon, ArrowRightIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { SessionProjectionPlan } from '../session/sessionProjectionTypes';
import { draftPlanReviewNotice } from '../session/sessionPlanApprovalModel';
import './SessionPlanDraftNotice.css';

type SessionPlanDraftNoticeProps = {
  plan: SessionProjectionPlan;
  onOpenPlanReview: () => void;
};

/** Inline, action-oriented surface for a persisted draft plan. The full
 * environment/permission reviewer stays in the Plan canvas tab; this notice
 * makes the gate discoverable from the conversation itself. */
export function SessionPlanDraftNotice({
  plan,
  onOpenPlanReview,
}: SessionPlanDraftNoticeProps) {
  const { t } = useI18n();
  const notice = draftPlanReviewNotice(plan);
  if (!notice) return null;

  return (
    <section
      className="session-plan-draft-notice"
      role="status"
      aria-live="polite"
      aria-label={t('session.planDraftReadyTitle')}
    >
      <span className="session-plan-draft-icon" aria-hidden="true">
        <ActivityLogIcon />
      </span>
      <div className="session-plan-draft-copy">
        <strong>{t('session.planDraftReadyTitle')}</strong>
        <span>{t('session.planDraftReadyDescription', { count: notice.taskCount })}</span>
        <ol>
          {notice.preview.map((step, index) => (
            <li key={index}>{step}</li>
          ))}
        </ol>
        {notice.remaining ? (
          <em>{t('session.planDraftReadyMore', { count: notice.remaining })}</em>
        ) : null}
      </div>
      <button
        type="button"
        className="session-plan-draft-action"
        onClick={onOpenPlanReview}
      >
        {t('session.planDraftReadyAction')}
        <ArrowRightIcon aria-hidden="true" />
      </button>
    </section>
  );
}
