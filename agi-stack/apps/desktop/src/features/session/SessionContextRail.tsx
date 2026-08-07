import { useEffect, useState } from 'react';
import { Button } from '@radix-ui/themes';
import {
  ActivityLogIcon,
  ArchiveIcon,
  ChatBubbleIcon,
  CheckCircledIcon,
  ChevronRightIcon,
  ClockIcon,
  CodeIcon,
  ExclamationTriangleIcon,
  GlobeIcon,
  LightningBoltIcon,
  Link2Icon,
  Pencil2Icon,
  StackIcon,
  TargetIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { SessionCanvasTabId } from './sessionCanvasModel';
import {
  sessionStatusPresentation,
  type SessionDetailViewModel,
  type SessionRunAction,
} from './sessionViewModel';
import { executionModeLabel, statusLabel } from './SessionWorkspace';
import './SessionContextRail.css';

type SessionContextRailProps = {
  viewModel: SessionDetailViewModel;
  runActionPending: SessionRunAction | null;
  onRunAction: (action: SessionRunAction, feedback?: string) => void;
  onOpenCanvas: (tab?: SessionCanvasTabId) => void;
};

/**
 * Session context rail hosted by the desktop right sidebar. The markup moved
 * here verbatim from SessionWorkspace; the review-feedback form state is now
 * local to the rail because the rail and the status banner render at the same
 * time (they used to be mutually exclusive surfaces).
 */
export function SessionContextRail({
  viewModel,
  runActionPending,
  onRunAction,
  onOpenCanvas,
}: SessionContextRailProps) {
  const { t } = useI18n();
  const [reviewFeedbackOpen, setReviewFeedbackOpen] = useState(false);
  const [reviewFeedback, setReviewFeedback] = useState('');
  const statusPresentation = sessionStatusPresentation(viewModel.status);
  const runActions = viewModel.runActions;
  const actionDisabled = runActionPending !== null || viewModel.runRevision === null;
  const evidenceSurface = viewModel.capabilityMode === 'code' ? 'checks' : 'verification';

  useEffect(() => {
    if (viewModel.status !== 'ready_review') {
      setReviewFeedbackOpen(false);
      setReviewFeedback('');
    }
  }, [viewModel.status]);

  return (
    <aside className="session-context-rail" aria-label={t('session.runContext')}>
      {statusPresentation ? (
        <section className={`session-context-attention tone-${statusPresentation.tone}`}>
          <header>
            <ExclamationTriangleIcon />
            <strong>{t(statusPresentation.titleKey)}</strong>
          </header>
          <p>
            {statusPresentation.tone === 'danger' && viewModel.error
              ? viewModel.error
              : t(statusPresentation.descriptionKey)}
          </p>
          <div className="session-context-attention-actions">
            {runActions.includes('request_changes') ? (
              <Button
                size="1"
                variant="surface"
                disabled={actionDisabled}
                onClick={() => setReviewFeedbackOpen(true)}
              >
                <Pencil2Icon /> {t('session.requestChanges')}
              </Button>
            ) : null}
            {runActions.includes('approve') ? (
              <Button
                size="1"
                color="green"
                disabled={actionDisabled}
                onClick={() => onRunAction('approve')}
              >
                <CheckCircledIcon />
                {runActionPending === 'approve'
                  ? t('session.approvingRun')
                  : t('session.approveRun')}
              </Button>
            ) : null}
            {!runActions.includes('approve') && !runActions.includes('request_changes') ? (
              <Button size="1" variant="surface" onClick={() => onOpenCanvas('plan')}>
                {t('session.reviewCanvas')}
              </Button>
            ) : null}
          </div>
          {reviewFeedbackOpen && runActions.includes('request_changes') ? (
            <form
              className="session-context-feedback"
              onSubmit={(event) => {
                event.preventDefault();
                const feedback = reviewFeedback.trim();
                if (!feedback) return;
                onRunAction('request_changes', feedback);
              }}
            >
              <label htmlFor="session-context-review-feedback">
                {t('session.changeRequestLabel')}
              </label>
              <textarea
                id="session-context-review-feedback"
                value={reviewFeedback}
                placeholder={t('session.changeRequestPlaceholder')}
                onChange={(event) => setReviewFeedback(event.target.value)}
              />
              <div>
                <Button
                  size="1"
                  type="button"
                  variant="ghost"
                  onClick={() => setReviewFeedbackOpen(false)}
                >
                  {t('session.cancelAction')}
                </Button>
                <Button
                  size="1"
                  type="submit"
                  disabled={!reviewFeedback.trim() || runActionPending !== null}
                >
                  {runActionPending === 'request_changes'
                    ? t('session.sendingChanges')
                    : t('session.sendChanges')}
                </Button>
              </div>
            </form>
          ) : null}
        </section>
      ) : null}

      <div className="session-context-card">
        <section className="session-context-section session-context-snapshot">
          <h2>{t('session.runSnapshot')}</h2>
          <ul className="session-context-rows">
            <li>
              <TargetIcon />
              <span>{t('session.overviewStatus')}</span>
              <strong>{statusLabel(viewModel.status, t)}</strong>
            </li>
            <li>
              <ChatBubbleIcon />
              <span>{t('session.conversation')}</span>
              <strong>
                {viewModel.capabilityMode === 'unavailable'
                  ? t('session.notAvailable')
                  : viewModel.capabilityMode === 'code'
                    ? t('session.code')
                    : t('session.work')}
              </strong>
            </li>
            <li>
              <LightningBoltIcon />
              <span>{t('session.runMode')}</span>
              <strong>
                {viewModel.executionMode === 'unavailable'
                  ? t('session.notAvailable')
                  : executionModeLabel(viewModel.executionMode, t)}
              </strong>
            </li>
            <li>
              <ClockIcon />
              <span>{t('session.elapsed')}</span>
              <strong>{viewModel.elapsedLabel ?? t('session.notAvailable')}</strong>
            </li>
            {viewModel.environmentLabel ? (
              <li>
                <GlobeIcon />
                <span>{t('session.overviewEnvironment')}</span>
                <strong title={viewModel.environmentLabel}>
                  {viewModel.environmentLabel}
                </strong>
              </li>
            ) : null}
          </ul>
        </section>

        <section className="session-context-section session-context-surfaces">
          <h2>{t('session.workSurfaces')}</h2>
          <button
            type="button"
            data-session-canvas-trigger="plan"
            onClick={() => onOpenCanvas('plan')}
          >
            <ActivityLogIcon />
            <strong>{t('session.canvasPlan')}</strong>
            <small>
              {viewModel.hasPlan ? t('session.planReady') : t('session.noPlanShort')}
            </small>
            <ChevronRightIcon />
          </button>
          <button
            type="button"
            data-session-canvas-trigger="output"
            onClick={() =>
              onOpenCanvas(viewModel.capabilityMode === 'code' ? 'changes' : 'artifacts')
            }
          >
            {viewModel.capabilityMode === 'code' ? <CodeIcon /> : <ArchiveIcon />}
            <strong>
              {viewModel.capabilityMode === 'code'
                ? t('session.canvasChanges')
                : t('session.canvasArtifacts')}
            </strong>
            <small>
              {viewModel.artifactCount === null
                ? t('session.notAvailable')
                : t('session.evidence.recordCount', { count: viewModel.artifactCount })}
            </small>
            <ChevronRightIcon />
          </button>
          <button
            type="button"
            data-session-canvas-trigger="evidence"
            onClick={() => onOpenCanvas(evidenceSurface)}
          >
            <CheckCircledIcon />
            <strong>
              {evidenceSurface === 'checks'
                ? t('session.canvasChecks')
                : t('session.canvasVerification')}
            </strong>
            <small>
              {viewModel.verificationCount === null
                ? t('session.notAvailable')
                : t('session.evidence.recordCount', {
                    count: viewModel.verificationCount,
                  })}
            </small>
            <ChevronRightIcon />
          </button>
        </section>

        <section className="session-context-section session-context-evidence">
          <h2>{t('session.latestEvidence')}</h2>
          <ul className="session-context-rows">
            <li>
              <StackIcon />
              <span>{t('session.toolActivity')}</span>
              <strong>
                {viewModel.toolActivityCount === null
                  ? t('session.notAvailable')
                  : viewModel.toolActivityCount}
              </strong>
            </li>
            <li>
              <ExclamationTriangleIcon />
              <span>{t('session.failedShort')}</span>
              <strong>
                {viewModel.failedToolActivityCount === null
                  ? t('session.notAvailable')
                  : viewModel.failedToolActivityCount}
              </strong>
            </li>
            <li>
              <Link2Icon />
              <span>{t('session.canvasSources')}</span>
              <strong>
                {viewModel.sourceCount === null
                  ? t('session.notAvailable')
                  : viewModel.sourceCount}
              </strong>
            </li>
          </ul>
        </section>
      </div>
    </aside>
  );
}
