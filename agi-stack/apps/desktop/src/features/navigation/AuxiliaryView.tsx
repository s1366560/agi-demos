import {
  DashboardIcon,
  LightningBoltIcon,
  MagnifyingGlassIcon,
  PlusIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import './AuxiliaryView.css';

export type AuxiliarySection = 'home' | 'automations' | 'search';
export type AuxiliaryMetricStatus = 'loading' | 'error' | 'ready';

type AuxiliaryViewProps = {
  section: AuxiliarySection;
  userName: string;
  runningCount: number;
  needsInputCount: number;
  readyCount: number;
  metricStatus: AuxiliaryMetricStatus;
  onOpenMyWork: () => void;
  onRetryMyWork: () => void;
};

const sectionIcons = {
  home: DashboardIcon,
  automations: LightningBoltIcon,
  search: MagnifyingGlassIcon,
} satisfies Record<AuxiliarySection, typeof DashboardIcon>;

export function AuxiliaryView({
  section,
  userName,
  runningCount,
  needsInputCount,
  readyCount,
  metricStatus,
  onOpenMyWork,
  onRetryMyWork,
}: AuxiliaryViewProps) {
  const { t } = useI18n();
  const Icon = sectionIcons[section];
  const title =
    section === 'home'
      ? t('auxiliary.homeTitle', { name: userName })
      : t(section === 'automations' ? 'nav.automations' : 'nav.search');
  const description =
    section === 'home'
      ? metricStatus === 'ready'
        ? t('auxiliary.homeDescription', { running: runningCount, ready: readyCount })
        : t(
            metricStatus === 'loading'
              ? 'auxiliary.metricsLoading'
              : 'auxiliary.metricsUnavailable',
          )
      : t(
          section === 'automations'
            ? 'auxiliary.automationsDescription'
            : 'auxiliary.searchDescription',
        );

  return (
    <section className="auxiliary-view" aria-labelledby="desktop-auxiliary-title">
      <header>
        <span>{t('auxiliary.eyebrow')}</span>
        <h1 id="desktop-auxiliary-title">{title}</h1>
        <p>{description}</p>
      </header>

      <section
        className="overview-grid"
        aria-busy={metricStatus === 'loading'}
        aria-label={t('auxiliary.summary')}
      >
        <article className="overview-hero">
          <Icon aria-hidden />
          <h2>{t('auxiliary.heroTitle')}</h2>
          <p>{t('auxiliary.heroDescription')}</p>
          <button type="button" onClick={onOpenMyWork}>
            <PlusIcon aria-hidden />
            {t('nav.myWork')}
          </button>
          {metricStatus !== 'ready' ? (
            <div
              className={`auxiliary-metric-status ${metricStatus}`}
              role={metricStatus === 'error' ? 'alert' : 'status'}
              aria-live="polite"
            >
              <span>
                {t(
                  metricStatus === 'loading'
                    ? 'auxiliary.metricsLoading'
                    : 'auxiliary.metricsUnavailable',
                )}
              </span>
              {metricStatus === 'error' ? (
                <button type="button" onClick={onRetryMyWork}>
                  {t('auxiliary.retryMetrics')}
                </button>
              ) : null}
            </div>
          ) : null}
        </article>

        <AuxiliaryMetric
          label={t('auxiliary.running')}
          value={runningCount}
          description={t('auxiliary.runningDescription')}
          status={metricStatus}
        />
        <AuxiliaryMetric
          label={t('auxiliary.needsInput')}
          value={needsInputCount}
          description={t('auxiliary.needsInputDescription')}
          status={metricStatus}
        />
        <AuxiliaryMetric
          label={t('auxiliary.ready')}
          value={readyCount}
          description={t('auxiliary.readyDescription')}
          status={metricStatus}
        />
      </section>
    </section>
  );
}

function AuxiliaryMetric({
  label,
  value,
  description,
  status,
}: {
  label: string;
  value: number;
  description: string;
  status: AuxiliaryMetricStatus;
}) {
  const { t } = useI18n();
  const metricDescription =
    status === 'ready'
      ? description
      : t(status === 'loading' ? 'auxiliary.metricPending' : 'auxiliary.metricUnavailable');

  return (
    <article>
      <span>{label}</span>
      <b>{status === 'ready' ? value : '—'}</b>
      <p>{metricDescription}</p>
    </article>
  );
}
