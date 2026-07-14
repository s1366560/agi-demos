import type { ComponentType, ReactNode } from 'react';

import {
  ActivityLogIcon,
  CheckCircledIcon,
  CodeIcon,
  DesktopIcon,
  ExclamationTriangleIcon,
  FileTextIcon,
  ReaderIcon,
  TargetIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { SessionCanvasTabId } from './sessionCanvasModel';
import { sessionInspectorSurfaceIds } from './sessionLayoutModel';
import {
  sessionStatusPresentation,
  type SessionDetailViewModel,
  type SessionStage,
} from './sessionViewModel';
import './SessionInspector.css';

export type SessionInspectorEvidence = {
  artifacts: number;
  changedFiles: number | null;
  checks: number | null;
};

type SessionInspectorProps = {
  viewModel: SessionDetailViewModel;
  evidence: SessionInspectorEvidence;
  onOpenCanvas: (tab: SessionCanvasTabId) => void;
};

type InspectorSurface = {
  id: SessionCanvasTabId;
  icon: ComponentType;
  labelKey: string;
  descriptionKey: string;
};

const stageOrder: Exclude<SessionStage, 'unavailable'>[] = [
  'understand',
  'implement',
  'verify',
  'review',
];

export function SessionInspector({
  viewModel,
  evidence,
  onOpenCanvas,
}: SessionInspectorProps) {
  const { t } = useI18n();
  const attention = sessionStatusPresentation(viewModel.status);
  const stageIndex = stageOrder.indexOf(
    viewModel.stage as Exclude<SessionStage, 'unavailable'>,
  );
  const stageProgress = stageIndex < 0 ? null : ((stageIndex + 1) / stageOrder.length) * 100;
  const surfaces = inspectorSurfaces(viewModel.capabilityMode);

  return (
    <aside className="session-context-inspector" aria-label={t('session.inspector')}>
      {attention?.tone === 'attention' ? (
        <section className="session-inspector-attention">
          <span>
            <ExclamationTriangleIcon /> {t('session.needsAttention')}
          </span>
          <strong>{t(attention.titleKey)}</strong>
          <p>{t(attention.descriptionKey)}</p>
        </section>
      ) : null}

      <section className="session-inspector-section session-inspector-run">
        <header>
          <span>{t('session.runSnapshot')}</span>
          <em data-status={viewModel.status}>{sessionStatusText(viewModel.status, t)}</em>
        </header>
        <div className="session-inspector-progress">
          <span>
            <i style={{ width: stageProgress === null ? '0%' : `${stageProgress}%` }} />
          </span>
          <b>
            {stageIndex < 0
              ? t('session.notAvailable')
              : `${stageIndex + 1} / ${stageOrder.length}`}
          </b>
        </div>
        <dl>
          <InspectorFact
            label={t('session.currentStage')}
            value={stageLabel(viewModel.stage, t)}
          />
          <InspectorFact
            icon={<DesktopIcon />}
            label={t('session.overviewEnvironment')}
            value={availableValue(viewModel.environmentLabel, 'Environment unavailable', t)}
          />
          <InspectorFact
            label={t('session.overviewPermission')}
            value={availableValue(viewModel.permissionLabel, 'Permission policy unavailable', t)}
          />
          <InspectorFact
            label={t('session.overviewModel')}
            value={availableValue(viewModel.modelLabel, 'Model unavailable', t)}
          />
          <InspectorFact
            label={t('session.elapsed')}
            value={availableValue(viewModel.elapsedLabel, 'Elapsed unavailable', t)}
          />
        </dl>
      </section>

      <section className="session-inspector-section session-inspector-surfaces">
        <header>
          <span>{t('session.workSurfaces')}</span>
          <small>{t('session.workSurfacesDescription')}</small>
        </header>
        <div>
          {surfaces.map(({ id, icon: Icon, labelKey, descriptionKey }) => (
            <button
              type="button"
              data-session-canvas-trigger={id}
              key={id}
              onClick={() => onOpenCanvas(id)}
            >
              <Icon />
              <span>
                <b>{t(labelKey)}</b>
                <small>{t(descriptionKey)}</small>
              </span>
              <ActivityLogIcon />
            </button>
          ))}
        </div>
      </section>

      <section className="session-inspector-section session-inspector-evidence">
        <header>
          <span>{t('session.latestEvidence')}</span>
        </header>
        <div>
          <EvidenceMetric
            icon={viewModel.capabilityMode === 'code' ? <CodeIcon /> : <FileTextIcon />}
            label={
              viewModel.capabilityMode === 'code'
                ? t('session.changedFilesLabel')
                : t('session.canvasArtifacts')
            }
            value={
              viewModel.capabilityMode === 'code' ? evidence.changedFiles : evidence.artifacts
            }
            t={t}
          />
          <EvidenceMetric
            icon={<CheckCircledIcon />}
            label={
              viewModel.capabilityMode === 'work'
                ? t('session.canvasVerification')
                : t('session.canvasChecks')
            }
            value={evidence.checks}
            t={t}
          />
        </div>
      </section>
    </aside>
  );
}

function InspectorFact({
  icon,
  label,
  value,
}: {
  icon?: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div>
      <dt>
        {icon} {label}
      </dt>
      <dd title={value}>{value}</dd>
    </div>
  );
}

function EvidenceMetric({
  icon,
  label,
  value,
  t,
}: {
  icon: ReactNode;
  label: string;
  value: number | null;
  t: (key: string, values?: Record<string, string | number>) => string;
}) {
  return (
    <div>
      {icon}
      <span>
        <b>{value === null ? t('session.notAvailable') : value.toLocaleString()}</b>
        <small>{label}</small>
      </span>
    </div>
  );
}

function inspectorSurfaces(mode: SessionDetailViewModel['capabilityMode']): InspectorSurface[] {
  const definitions: Partial<Record<SessionCanvasTabId, Omit<InspectorSurface, 'id'>>> = {
    plan: surfaceDefinition(TargetIcon, 'session.canvasPlan', 'session.inspectPlanDescription'),
    changes: surfaceDefinition(
      CodeIcon,
      'session.canvasChanges',
      'session.inspectChangesDescription',
    ),
    checks: surfaceDefinition(
      CheckCircledIcon,
      'session.canvasChecks',
      'session.inspectChecksDescription',
    ),
    artifacts: surfaceDefinition(
      mode === 'unavailable' ? ReaderIcon : FileTextIcon,
      'session.canvasArtifacts',
      'session.inspectArtifactsDescription',
    ),
    verification: surfaceDefinition(
      CheckCircledIcon,
      'session.canvasVerification',
      'session.inspectChecksDescription',
    ),
    activity: surfaceDefinition(
      ActivityLogIcon,
      'session.canvasActivity',
      'session.inspectActivityDescription',
    ),
  };

  return sessionInspectorSurfaceIds(mode).flatMap((id) => {
    const definition = definitions[id];
    return definition ? [{ id, ...definition }] : [];
  });
}

function surfaceDefinition(
  icon: ComponentType,
  labelKey: string,
  descriptionKey: string,
): Omit<InspectorSurface, 'id'> {
  return { icon, labelKey, descriptionKey };
}

function sessionStatusText(
  status: string,
  t: (key: string, values?: Record<string, string | number>) => string,
) {
  const keys: Record<string, string> = {
    unavailable: 'session.notAvailable',
    active: 'session.statusActive',
    queued: 'session.statusQueued',
    running: 'session.statusRunning',
    completed: 'session.statusCompleted',
    blocked: 'session.statusBlocked',
    needs_input: 'session.statusNeedsInput',
    needs_approval: 'session.statusNeedsApproval',
    paused: 'session.statusPaused',
    ready_review: 'session.statusReadyReview',
    failed: 'session.statusFailed',
    interrupted: 'session.statusInterrupted',
    disconnected: 'session.statusDisconnected',
    cancelled: 'session.statusCancelled',
  };
  return keys[status] ? t(keys[status]) : status;
}

function stageLabel(
  stage: SessionStage,
  t: (key: string, values?: Record<string, string | number>) => string,
) {
  if (stage === 'understand') return t('session.stageUnderstand');
  if (stage === 'implement') return t('session.stageImplement');
  if (stage === 'verify') return t('session.stageVerify');
  if (stage === 'review') return t('session.stageReview');
  return t('session.notAvailable');
}

function availableValue(
  value: string,
  unavailableValue: string,
  t: (key: string, values?: Record<string, string | number>) => string,
) {
  return value === unavailableValue ? t('session.notAvailable') : value;
}
