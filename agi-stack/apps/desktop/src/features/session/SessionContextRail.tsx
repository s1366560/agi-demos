import { useEffect, useState } from 'react';
import { Button } from '@radix-ui/themes';
import {
  CheckCircledIcon,
  ChevronRightIcon,
  CodeIcon,
  ExclamationTriangleIcon,
  FileTextIcon,
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
  type SessionStage,
} from './sessionViewModel';
import { executionModeLabel, statusLabel } from './SessionWorkspace';
import './SessionContextRail.css';

type SessionContextRailProps = {
  viewModel: SessionDetailViewModel;
  runActionPending: SessionRunAction | null;
  onRunAction: (action: SessionRunAction, feedback?: string) => void;
  onOpenCanvas: (tab?: SessionCanvasTabId) => void;
};

// prototype mission-control refactor 2026-09: the run snapshot progress bar
// counts stages (understand → review); terminal-ready runs read 4 / 4.
const SNAPSHOT_STAGE_ORDER: Array<Exclude<SessionStage, 'unavailable'>> = [
  'understand',
  'implement',
  'verify',
  'review',
];
const SNAPSHOT_STAGE_LABELS: Record<Exclude<SessionStage, 'unavailable'>, string> = {
  understand: 'session.stageUnderstand',
  implement: 'session.stageImplement',
  verify: 'session.stageVerify',
  review: 'session.stageReview',
};

function snapshotProgress(viewModel: SessionDetailViewModel): { count: number; percent: number } | null {
  if (viewModel.stage === 'unavailable') return null;
  const complete =
    viewModel.status === 'ready_review' ||
    viewModel.status === 'completed' ||
    viewModel.status === 'accepted';
  const count = complete
    ? SNAPSHOT_STAGE_ORDER.length
    : SNAPSHOT_STAGE_ORDER.indexOf(viewModel.stage) + 1;
  return { count, percent: (count / SNAPSHOT_STAGE_ORDER.length) * 100 };
}

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
  const progress = snapshotProgress(viewModel);

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
            {statusPresentation.tone === 'success' ? (
              <CheckCircledIcon />
            ) : (
              <ExclamationTriangleIcon />
            )}
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
          <header>
            <h2>{t('session.runSnapshot')}</h2>
            <em>{statusLabel(viewModel.status, t)}</em>
          </header>
          {progress ? (
            <div className="session-context-progress">
              <span>
                <i style={{ width: `${progress.percent}%` }} />
              </span>
              <b>
                {progress.count} / {SNAPSHOT_STAGE_ORDER.length}
              </b>
            </div>
          ) : null}
          <dl className="session-context-facts">
            <div>
              <dt>{t('session.currentStage')}</dt>
              <dd>
                {viewModel.stage === 'unavailable'
                  ? t('session.notAvailable')
                  : t(SNAPSHOT_STAGE_LABELS[viewModel.stage])}
              </dd>
            </div>
            <div>
              <dt>{t('session.overviewEnvironment')}</dt>
              <dd title={viewModel.environmentLabel ?? undefined}>
                {viewModel.environmentLabel ?? t('session.notAvailable')}
              </dd>
            </div>
            <div>
              <dt>{t('session.elapsed')}</dt>
              <dd>{viewModel.elapsedLabel ?? t('session.notAvailable')}</dd>
            </div>
            <div>
              <dt>{t('session.runMode')}</dt>
              <dd>
                {viewModel.executionMode === 'unavailable'
                  ? t('session.notAvailable')
                  : executionModeLabel(viewModel.executionMode, t)}
              </dd>
            </div>
            <div>
              <dt>{t('session.permission')}</dt>
              <dd>{viewModel.permissionLabel ?? t('session.notAvailable')}</dd>
            </div>
          </dl>
        </section>

        <section className="session-context-section session-context-surfaces">
          <header>
            <h2>{t('session.workSurfaces')}</h2>
            <small>{t('session.workSurfacesDescription')}</small>
          </header>
          <div className="session-context-surfaces-list">
            <button
              type="button"
              data-session-canvas-trigger="plan"
              onClick={() => onOpenCanvas('plan')}
            >
              <TargetIcon />
              <span>
                <b>{t('session.canvasPlan')}</b>
                <small>
                  {viewModel.hasPlan
                    ? t('session.inspectPlanDescription')
                    : t('session.noPlanShort')}
                </small>
              </span>
              <ChevronRightIcon />
            </button>
            <button
              type="button"
              data-session-canvas-trigger="output"
              onClick={() =>
                onOpenCanvas(viewModel.capabilityMode === 'code' ? 'changes' : 'artifacts')
              }
            >
              {viewModel.capabilityMode === 'code' ? <CodeIcon /> : <FileTextIcon />}
              <span>
                <b>
                  {viewModel.capabilityMode === 'code'
                    ? t('session.canvasChanges')
                    : t('session.canvasArtifacts')}
                </b>
                <small>
                  {viewModel.capabilityMode === 'code'
                    ? t('session.inspectChangesDescription')
                    : t('session.inspectArtifactsDescription')}
                </small>
              </span>
              <ChevronRightIcon />
            </button>
            <button
              type="button"
              data-session-canvas-trigger="evidence"
              onClick={() => onOpenCanvas(evidenceSurface)}
            >
              <CheckCircledIcon />
              <span>
                <b>
                  {evidenceSurface === 'checks'
                    ? t('session.canvasChecks')
                    : t('session.canvasVerification')}
                </b>
                <small>{t('session.inspectChecksDescription')}</small>
              </span>
              <ChevronRightIcon />
            </button>
          </div>
        </section>

        <section className="session-context-section session-context-evidence">
          <header>
            <h2>{t('session.latestEvidence')}</h2>
          </header>
          <div className="session-context-evidence-summary">
            <CheckCircledIcon />
            <span>
              <b>
                {viewModel.sourceCount === null
                  ? t('session.notAvailable')
                  : t('session.linkedClaimCount', { count: viewModel.sourceCount })}
              </b>
              <small>{t('session.evidenceCoverage')}</small>
            </span>
          </div>
          <ul className="session-context-rows">
            <li>
              <StackIcon />
              <span>{t('session.loadedToolActivity')}</span>
              <strong>
                {viewModel.observedToolActivityCount === null
                  ? t('session.notAvailable')
                  : viewModel.observedToolActivityCount}
              </strong>
            </li>
            <li>
              <ExclamationTriangleIcon />
              <span>{t('session.loadedFailedToolActivity')}</span>
              <strong>
                {viewModel.observedFailedToolActivityCount === null
                  ? t('session.notAvailable')
                  : viewModel.observedFailedToolActivityCount}
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
