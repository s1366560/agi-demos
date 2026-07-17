import { Badge } from '@radix-ui/themes';
import {
  CheckCircledIcon,
  ExclamationTriangleIcon,
  FileTextIcon,
  ReaderIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { DesktopArtifactVersion } from '../../types';
import {
  artifactEvidenceForCurrentVersions,
  type ArtifactEvidenceCollection,
  type ArtifactEvidenceRow,
} from './sessionEvidenceModel';
import './SessionEvidenceCanvas.css';

type SessionEvidenceCanvasProps = {
  collection: ArtifactEvidenceCollection;
  presentation: 'sources' | 'checks' | 'verification';
  versions: DesktopArtifactVersion[];
  available: boolean;
  onOpenArtifact: (artifactVersionId: string) => void;
};

function statusColor(status: string | null): 'green' | 'red' | 'amber' | 'gray' {
  const value = status?.toLowerCase();
  if (value === 'passed' || value === 'success' || value === 'completed') return 'green';
  if (value === 'failed' || value === 'error') return 'red';
  if (value === 'blocked' || value === 'warning') return 'amber';
  return 'gray';
}

function serializedEvidence(value: unknown): string {
  const serialized = JSON.stringify(value, null, 2);
  return serialized === undefined ? String(value) : serialized;
}

function evidenceLocation(row: ArtifactEvidenceRow): string | null {
  const location = row.uri ?? row.path;
  if (!location) return null;
  return row.line === null ? location : `${location}:${row.line}`;
}

export function SessionEvidenceCanvas({
  collection,
  presentation,
  versions,
  available,
  onOpenArtifact,
}: SessionEvidenceCanvasProps) {
  const { t } = useI18n();
  const model = artifactEvidenceForCurrentVersions(versions, collection);
  const title = t(`session.evidence.${presentation}.title`);
  const description = t(`session.evidence.${presentation}.description`);
  const Icon = collection === 'sources' ? ReaderIcon : CheckCircledIcon;

  return (
    <section className="session-evidence-canvas" aria-label={title}>
      <header className="session-evidence-header">
        <span className="session-evidence-heading-icon" aria-hidden>
          <Icon />
        </span>
        <div>
          <strong>{title}</strong>
          <small>{description}</small>
        </div>
        <Badge color={available && model.rows.length ? 'cyan' : 'gray'} variant="soft">
          {available
            ? t('session.evidence.recordCount', { count: model.rows.length })
            : t('session.notAvailable')}
        </Badge>
      </header>

      {!available ? (
        <div className="session-evidence-empty">
          <ExclamationTriangleIcon />
          <strong>{t('session.dataUnavailableTitle')}</strong>
          <p>{t('session.dataUnavailableDescription')}</p>
        </div>
      ) : !model.currentVersions.length ? (
        <div className="session-evidence-empty">
          <FileTextIcon />
          <strong>{t('session.evidence.noArtifacts')}</strong>
          <p>{t('session.evidence.noArtifactsDescription')}</p>
        </div>
      ) : (
        <div className="session-evidence-list">
          {model.rows.map((row) => {
            const location = evidenceLocation(row);
            return (
              <article
                className="session-evidence-record"
                data-artifact-id={row.artifactId}
                data-artifact-version-id={row.artifactVersionId}
                data-artifact-revision={row.revision}
                key={`${row.artifactVersionId}:${row.evidenceId}`}
              >
                <button type="button" onClick={() => onOpenArtifact(row.artifactVersionId)}>
                  <span className="session-evidence-record-icon" aria-hidden>
                    <Icon />
                  </span>
                  <span className="session-evidence-record-main">
                    <strong>{row.label ?? t('session.evidence.unlabeled')}</strong>
                    <small>
                      {row.kind} · {row.evidenceId}
                    </small>
                    {location ? <code title={location}>{location}</code> : null}
                  </span>
                  <span className="session-evidence-record-meta">
                    <Badge color={statusColor(row.status)} variant="soft">
                      {row.status ?? t('session.evidence.statusUnknown')}
                    </Badge>
                    <small>
                      {row.filename} · v{row.version}
                    </small>
                    <code title={row.artifactVersionId}>{row.artifactVersionId}</code>
                  </span>
                </button>
                <details>
                  <summary>{t('session.evidence.raw')}</summary>
                  <pre>{serializedEvidence(row.raw)}</pre>
                </details>
              </article>
            );
          })}

          {model.missing.map((missing) => (
            <article
              className="session-evidence-record missing"
              data-artifact-id={missing.artifactId}
              data-artifact-version-id={missing.artifactVersionId}
              data-artifact-revision={missing.revision}
              key={`${missing.artifactVersionId}:missing:${collection}`}
            >
              <button type="button" onClick={() => onOpenArtifact(missing.artifactVersionId)}>
                <span className="session-evidence-record-icon" aria-hidden>
                  <ExclamationTriangleIcon />
                </span>
                <span className="session-evidence-record-main">
                  <strong>{missing.filename}</strong>
                  <small>{t(`session.evidence.${collection}.missingDescription`)}</small>
                </span>
                <span className="session-evidence-record-meta">
                  <Badge color="amber" variant="soft">
                    {t('session.evidence.missing')}
                  </Badge>
                  <small>
                    v{missing.version}
                  </small>
                  <code title={missing.artifactVersionId}>{missing.artifactVersionId}</code>
                </span>
              </button>
            </article>
          ))}
        </div>
      )}

      {available && model.currentVersions.length ? (
        <footer>
          <span>
            {t('session.evidence.currentArtifactCount', {
              count: model.currentVersions.length,
            })}
          </span>
          <small>{t('session.evidence.currentOnly')}</small>
        </footer>
      ) : null}
    </section>
  );
}
