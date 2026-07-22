import { useMemo, useState } from 'react';
import {
  ActivityLogIcon,
  CodeIcon,
  CubeIcon,
  DesktopIcon,
  GlobeIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  SessionRuntimeInfrastructureModel,
  SessionRuntimeResource,
  SessionRuntimeResourceFamily,
} from './sessionRuntimeInfrastructureModel';
import './SessionRuntimeInfrastructureCanvas.css';

type Selection = `resource:${string}` | `event:${string}`;

const statusTranslationKeys = new Set([
  'running',
  'ready',
  'connected',
  'starting',
  'stopped',
  'terminated',
  'error',
]);

export function SessionRuntimeInfrastructureCanvas({
  model,
}: {
  model: SessionRuntimeInfrastructureModel;
}) {
  const { t } = useI18n();
  const [selection, setSelection] = useState<Selection | null>(null);
  const fallbackSelection = model.events.at(-1) ? `event:${model.events.at(-1)?.id}` : null;
  const effectiveSelection = selection ?? fallbackSelection;
  const selectedEvent = useMemo(
    () =>
      effectiveSelection?.startsWith('event:')
        ? (model.events.find((event) => `event:${event.id}` === effectiveSelection) ?? null)
        : null,
    [effectiveSelection, model.events],
  );
  const selectedResource = useMemo(
    () =>
      effectiveSelection?.startsWith('resource:')
        ? (model.resources.find(
            (resource) => `resource:${resource.key}` === effectiveSelection,
          ) ?? null)
        : (selectedEvent?.snapshot ?? null),
    [effectiveSelection, model.resources, selectedEvent],
  );
  const historyEvents = useMemo(
    () => [...model.events].sort((left, right) => right.eventTimeUs - left.eventTimeUs),
    [model.events],
  );
  const statusLabel = (status: string) =>
    statusTranslationKeys.has(status)
      ? t(`session.runtime.status.${status}`)
      : status || t('session.runtime.status.unknown');

  if (!model.events.length) {
    return (
      <section
        className="session-runtime-infrastructure-canvas is-empty"
        aria-label={t('session.runtime.title')}
      >
        <CubeIcon aria-hidden="true" />
        <h2>{t('session.runtime.empty')}</h2>
        <p>{t('session.runtime.emptyDescription')}</p>
      </section>
    );
  }

  return (
    <section
      className="session-runtime-infrastructure-canvas"
      aria-label={t('session.runtime.title')}
    >
      <header className="session-runtime-header">
        <div className="session-runtime-heading">
          <span aria-hidden="true"><CubeIcon /></span>
          <div>
            <small>{t('session.runtime.kicker')}</small>
            <h2>{t('session.runtime.title')}</h2>
          </div>
        </div>
        {model.activeSandbox ? (
          <div className="session-runtime-active-sandbox">
            <small>{t('session.runtime.activeSandbox')}</small>
            <code>{model.activeSandbox.id}</code>
            <RuntimeStatus status={model.activeSandbox.status} label={statusLabel(model.activeSandbox.status)} />
          </div>
        ) : null}
      </header>

      <div className="session-runtime-summary" aria-label={t('session.runtime.summary')}>
        <RuntimeMetric label={t('session.runtime.events')} value={model.summary.events} />
        <RuntimeMetric label={t('session.runtime.resources')} value={model.summary.resources} />
        <RuntimeMetric label={t('session.runtime.running')} value={model.summary.running} />
        <RuntimeMetric
          className={model.summary.errors ? 'is-error' : undefined}
          label={t('session.runtime.errors')}
          value={model.summary.errors}
        />
      </div>

      <div className="session-runtime-layout">
        <article className="session-runtime-section session-runtime-topology">
          <SectionHeader
            icon={<ActivityLogIcon />}
            title={t('session.runtime.topology')}
            description={t('session.runtime.topologyDescription')}
          />
          <div className="session-runtime-resource-list">
            {model.resources.map((resource) => {
              const selected = effectiveSelection === `resource:${resource.key}`;
              return (
                <button
                  key={resource.key}
                  type="button"
                  className={`session-runtime-resource ${selected ? 'selected' : ''}`}
                  aria-pressed={selected}
                  onClick={() => setSelection(`resource:${resource.key}`)}
                >
                  <span className={`family-icon family-${resource.family}`} aria-hidden="true">
                    <RuntimeFamilyIcon family={resource.family} />
                  </span>
                  <span>
                    <small>{t(`session.runtime.family.${resource.family}`)}</small>
                    <strong>{resource.label}</strong>
                    <code>{resource.id}</code>
                  </span>
                  <RuntimeStatus status={resource.status} label={statusLabel(resource.status)} />
                </button>
              );
            })}
          </div>
        </article>

        <article className="session-runtime-section session-runtime-evidence">
          <SectionHeader
            icon={<CubeIcon />}
            title={t('session.runtime.selectedEvidence')}
            description={t('session.runtime.selectedEvidenceDescription')}
          />
          {selectedResource ? (
            <RuntimeEvidence
              resource={selectedResource}
              eventType={selectedEvent?.type ?? null}
              statusLabel={statusLabel(selectedResource.status)}
              t={t}
            />
          ) : (
            <p className="session-runtime-empty-copy">{t('session.runtime.noEvidence')}</p>
          )}
        </article>
      </div>

      <article className="session-runtime-section session-runtime-history">
        <SectionHeader
          icon={<ActivityLogIcon />}
          title={t('session.runtime.history')}
          description={t('session.runtime.historyDescription')}
        />
        <div className="session-runtime-history-list">
          {historyEvents.map((event) => {
            const selected = effectiveSelection === `event:${event.id}`;
            return (
              <button
                key={event.id}
                type="button"
                className={selected ? 'selected' : undefined}
                aria-pressed={selected}
                onClick={() => setSelection(`event:${event.id}`)}
              >
                <span className={`family-icon family-${event.family}`} aria-hidden="true">
                  <RuntimeFamilyIcon family={event.family} />
                </span>
                <span>
                  <strong>{event.type}</strong>
                  <small>{event.snapshot.label}</small>
                </span>
                <time>{formatRuntimeTime(event.eventTimeUs)}</time>
                <RuntimeStatus status={event.status} label={statusLabel(event.status)} />
              </button>
            );
          })}
        </div>
      </article>
    </section>
  );
}

function RuntimeEvidence({
  resource,
  eventType,
  statusLabel,
  t,
}: {
  resource: SessionRuntimeResource;
  eventType: string | null;
  statusLabel: string;
  t: (key: string, values?: Record<string, string | number>) => string;
}) {
  const facts: Array<[string, string | number | null]> = [
    [t('session.runtime.eventType'), eventType],
    [t('session.runtime.status'), statusLabel],
    [t('session.runtime.sandboxId'), resource.sandboxId],
    [t('session.runtime.endpoint'), resource.endpoint],
    [t('session.runtime.websocketUrl'), resource.websocketUrl],
    [t('session.runtime.url'), resource.url],
    [t('session.runtime.proxyUrl'), resource.proxyUrl],
    [t('session.runtime.wsProxyUrl'), resource.wsProxyUrl],
    [t('session.runtime.display'), resource.display],
    [t('session.runtime.resolution'), resource.resolution],
    [t('session.runtime.port'), resource.port],
    [t('session.runtime.sessionId'), resource.sessionId],
    [t('session.runtime.pid'), resource.pid],
    [t('session.runtime.sourceType'), resource.sourceType],
    [
      t('session.runtime.autoOpen'),
      resource.autoOpen === null
        ? null
        : t(resource.autoOpen ? 'session.runtime.enabled' : 'session.runtime.disabled'),
    ],
    [t('session.runtime.updated'), formatRuntimeTime(resource.updatedAtUs)],
  ];

  return (
    <div className="session-runtime-evidence-body">
      <div className="session-runtime-evidence-title">
        <span className={`family-icon family-${resource.family}`} aria-hidden="true">
          <RuntimeFamilyIcon family={resource.family} />
        </span>
        <span>
          <small>{t(`session.runtime.family.${resource.family}`)}</small>
          <h3>{resource.label}</h3>
        </span>
      </div>
      {resource.errorMessage ? (
        <p className="session-runtime-error-message">{resource.errorMessage}</p>
      ) : null}
      <dl>
        {facts.map(([label, value]) =>
          value === null ? null : (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ),
        )}
      </dl>
    </div>
  );
}

function RuntimeFamilyIcon({ family }: { family: SessionRuntimeResourceFamily }) {
  if (family === 'desktop') return <DesktopIcon />;
  if (family === 'terminal') return <CodeIcon />;
  if (family === 'httpService') return <GlobeIcon />;
  return <CubeIcon />;
}

function RuntimeStatus({ status, label }: { status: string; label: string }) {
  return <span className={`session-runtime-status status-${status}`}>{label}</span>;
}

function RuntimeMetric({
  label,
  value,
  className,
}: {
  label: string;
  value: number;
  className?: string;
}) {
  return (
    <div className={className}>
      <strong>{value.toLocaleString()}</strong>
      <small>{label}</small>
    </div>
  );
}

function SectionHeader({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <header>
      <span aria-hidden="true">{icon}</span>
      <div>
        <h3>{title}</h3>
        <small>{description}</small>
      </div>
    </header>
  );
}

function formatRuntimeTime(eventTimeUs: number): string {
  if (!eventTimeUs) return '—';
  return new Date(eventTimeUs / 1000).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}
