import {
  BarChartIcon,
  ClockIcon,
  CubeIcon,
  ExclamationTriangleIcon,
  FileTextIcon,
  LockClosedIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';
import { Button } from '@radix-ui/themes';

import { useI18n } from '../../i18n';
import type {
  ProjectOverviewAvailability,
  ProjectOverviewPresentationModel,
  ProjectOverviewRecentItem,
  ProjectOverviewSummaryField,
} from './projectOverviewPresentationModel';
import './ProjectOverviewPage.css';

type ProjectOverviewPageProps = Readonly<{
  model: ProjectOverviewPresentationModel;
  onRetry: () => void;
}>;

export function ProjectOverviewPage({ model, onRetry }: ProjectOverviewPageProps) {
  const { locale, t } = useI18n();

  if (model.state !== 'ready' && model.state !== 'degraded') {
    return <ProjectOverviewState model={model} onRetry={onRetry} />;
  }

  const projectName = model.project?.name ?? model.scope.projectId;
  const projectDescription =
    model.project?.description ?? t('projectOverview.projectDescriptionUnavailable');

  return (
    <section
      className="project-overview-page"
      data-authority={model.authority}
      data-state={model.state}
    >
      <header className="project-overview-header">
        <div className="project-overview-heading">
          <span className="project-overview-eyebrow">{t('projectOverview.eyebrow')}</span>
          <div className="project-overview-title-row">
            <h1>{projectName}</h1>
            <AuthorityBadge authority={model.authority} />
          </div>
          <p>{projectDescription}</p>
          <div className="project-overview-scope">
            <span>{t('projectOverview.projectScope')}</span>
            <code>{model.scope.projectId}</code>
            {model.project?.createdAt ? (
              <span>
                {t('projectOverview.created', {
                  date: formatDate(model.project.createdAt, locale),
                })}
              </span>
            ) : null}
          </div>
        </div>
      </header>

      {model.state === 'degraded' ? (
        <section className="project-overview-degraded" role="status">
          <ExclamationTriangleIcon aria-hidden="true" />
          <div>
            <strong>{t('projectOverview.degraded.title')}</strong>
            <p>{t('projectOverview.degraded.description')}</p>
            <ReasonCode reasonCode={model.reasonCode} />
          </div>
        </section>
      ) : null}

      <section
        className="project-overview-summary"
        aria-labelledby="project-overview-summary-title"
      >
        <div className="project-overview-section-heading">
          <div>
            <span>{t('projectOverview.summary.eyebrow')}</span>
            <h2 id="project-overview-summary-title">{t('projectOverview.summary.title')}</h2>
          </div>
        </div>
        <div className="project-overview-summary-grid">
          {model.summaryFields.map((field) => (
            <SummaryField key={field.id} field={field} locale={locale} />
          ))}
        </div>
      </section>

      <RecentItems model={model} locale={locale} />
    </section>
  );
}

function ProjectOverviewState({
  model,
  onRetry,
}: Pick<ProjectOverviewPageProps, 'model' | 'onRetry'>) {
  const { t } = useI18n();
  const copy = stateCopy(model.state);
  const busy = model.state === 'loading' || model.state === 'scope_switch';
  const alert =
    model.state === 'error' ||
    model.state === 'forbidden' ||
    model.state === 'unavailable';
  const Icon = stateIcon(model.state);

  return (
    <section
      className="project-overview-page project-overview-state-page"
      data-authority={model.authority}
      data-state={model.state}
      aria-busy={busy || undefined}
    >
      <div className="project-overview-state-card" role={alert ? 'alert' : 'status'}>
        <span className="project-overview-state-icon">
          <Icon aria-hidden="true" />
        </span>
        <span className="project-overview-eyebrow">
          {model.authority === 'cloud'
            ? t('projectOverview.authority.cloud')
            : t('projectOverview.authority.local')}
        </span>
        <h1>{t(copy.titleKey)}</h1>
        <p>{t(copy.descriptionKey)}</p>
        <code className="project-overview-state-scope">{model.scope.projectId}</code>
        {model.detail ? <p className="project-overview-state-detail">{model.detail}</p> : null}
        <ReasonCode reasonCode={model.reasonCode} />
        {model.retryVisible ? (
          <Button variant="surface" color="gray" onClick={onRetry}>
            <ReloadIcon aria-hidden="true" />
            {t('common.retry')}
          </Button>
        ) : null}
      </div>
    </section>
  );
}

function AuthorityBadge({ authority }: Pick<ProjectOverviewPresentationModel, 'authority'>) {
  const { t } = useI18n();
  return (
    <span className="project-overview-authority" data-authority={authority}>
      {authority === 'cloud'
        ? t('projectOverview.authority.cloud')
        : t('projectOverview.authority.local')}
    </span>
  );
}

function SummaryField({
  field,
  locale,
}: Readonly<{
  field: ProjectOverviewSummaryField;
  locale: string;
}>) {
  const { t } = useI18n();
  const available = field.availability === 'available' && field.value !== null;

  return (
    <article
      className="project-overview-summary-card"
      data-availability={field.availability}
    >
      <div className="project-overview-summary-card-heading">
        <MetricIcon id={field.id} />
        <span>{t(field.labelKey)}</span>
      </div>
      {available ? (
        <strong>{formatFieldValue(field, locale)}</strong>
      ) : (
        <strong>{t(availabilityKey(field.availability))}</strong>
      )}
      <div className="project-overview-field-authority">
        <span>{t(availabilityKey(field.availability))}</span>
        <ReasonCode reasonCode={field.reasonCode} />
      </div>
    </article>
  );
}

function RecentItems({
  model,
  locale,
}: Readonly<{
  model: ProjectOverviewPresentationModel;
  locale: string;
}>) {
  const { t } = useI18n();
  const local = model.recent.kind === 'knowledge_items';
  const titleKey = local
    ? 'projectOverview.local.recentKnowledgeItems'
    : 'projectOverview.cloud.latestMemories';
  const emptyTitleKey = local
    ? 'projectOverview.local.noRecentKnowledgeItems'
    : 'projectOverview.cloud.noRecentMemories';
  const emptyDescriptionKey = local
    ? 'projectOverview.local.noRecentKnowledgeItemsDescription'
    : 'projectOverview.cloud.noRecentMemoriesDescription';

  return (
    <section
      className="project-overview-recent"
      aria-labelledby="project-overview-recent-title"
      data-kind={model.recent.kind}
    >
      <div className="project-overview-section-heading">
        <div>
          <span>{t('projectOverview.recent.eyebrow')}</span>
          <h2 id="project-overview-recent-title">{t(titleKey)}</h2>
        </div>
        <span>
          {t('projectOverview.recent.total', {
            count: model.recent.total,
          })}
        </span>
      </div>

      {model.recent.availability !== 'available' ? (
        <div
          className="project-overview-recent-authority"
          data-availability={model.recent.availability}
        >
          <strong>{t(availabilityKey(model.recent.availability))}</strong>
          <ReasonCode reasonCode={model.recent.reasonCode} />
        </div>
      ) : null}

      {model.recent.items.length === 0 ? (
        <div className="project-overview-recent-empty" role="status">
          <FileTextIcon aria-hidden="true" />
          <div>
            <strong>{t(emptyTitleKey)}</strong>
            <p>{t(emptyDescriptionKey)}</p>
          </div>
        </div>
      ) : (
        <div className="project-overview-recent-list">
          {model.recent.items.map((item) => (
            <RecentItem
              key={item.id}
              item={item}
              kind={model.recent.kind}
              locale={locale}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function RecentItem({
  item,
  kind,
  locale,
}: Readonly<{
  item: ProjectOverviewRecentItem;
  kind: ProjectOverviewPresentationModel['recent']['kind'];
  locale: string;
}>) {
  const { t } = useI18n();
  return (
    <article className="project-overview-recent-item">
      <div className="project-overview-recent-item-copy">
        <span className="project-overview-recent-kind">
          {kind === 'knowledge_items'
            ? t('projectOverview.local.knowledgeItem')
            : t('projectOverview.cloud.memory')}
        </span>
        <h3>{item.title}</h3>
        <p>{item.content}</p>
        {item.tags.length > 0 ? (
          <div className="project-overview-tags">
            {item.tags.map((tag) => (
              <span key={tag}>{tag}</span>
            ))}
          </div>
        ) : null}
      </div>
      <div className="project-overview-recent-meta">
        {item.source ? <code>{item.source}</code> : null}
        {item.status ? <span>{item.status}</span> : null}
        {item.createdAt ? (
          <span>
            <ClockIcon aria-hidden="true" />
            {formatDate(item.createdAt, locale)}
          </span>
        ) : null}
      </div>
    </article>
  );
}

function ReasonCode({ reasonCode }: Readonly<{ reasonCode: string | null }>) {
  const { t } = useI18n();
  if (!reasonCode) return null;
  return (
    <span className="project-overview-reason">
      <span>{t('projectOverview.reasonCode')}</span>
      <code>{reasonCode}</code>
    </span>
  );
}

function MetricIcon({ id }: Pick<ProjectOverviewSummaryField, 'id'>) {
  if (id === 'memory_count' || id === 'conversation_count') {
    return <FileTextIcon aria-hidden="true" />;
  }
  if (id === 'storage' || id === 'storage_quota') {
    return <CubeIcon aria-hidden="true" />;
  }
  return <BarChartIcon aria-hidden="true" />;
}

function formatFieldValue(field: ProjectOverviewSummaryField, locale: string): string {
  if (field.value === null) return '';
  if (field.valueKind === 'bytes_pair' && field.secondaryValue !== null) {
    return `${formatBytes(field.value, locale)} / ${formatBytes(field.secondaryValue, locale)}`;
  }
  return new Intl.NumberFormat(locale).format(field.value);
}

function formatBytes(value: number, locale: string): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'] as const;
  if (value === 0) return '0 B';
  const unitIndex = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  const normalized = value / 1024 ** unitIndex;
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(normalized)} ${units[unitIndex]}`;
}

function formatDate(value: string, locale: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(date);
}

function availabilityKey(availability: ProjectOverviewAvailability): string {
  switch (availability) {
    case 'available':
      return 'projectOverview.availability.available';
    case 'degraded':
      return 'projectOverview.availability.degraded';
    case 'unavailable':
      return 'projectOverview.availability.unavailable';
    case 'not_applicable':
      return 'projectOverview.availability.notApplicable';
  }
}

function stateCopy(state: ProjectOverviewPresentationModel['state']): {
  titleKey: string;
  descriptionKey: string;
} {
  switch (state) {
    case 'loading':
      return {
        titleKey: 'projectOverview.loading.title',
        descriptionKey: 'projectOverview.loading.description',
      };
    case 'scope_switch':
      return {
        titleKey: 'projectOverview.scopeSwitch.title',
        descriptionKey: 'projectOverview.scopeSwitch.description',
      };
    case 'empty':
      return {
        titleKey: 'projectOverview.state.empty.title',
        descriptionKey: 'projectOverview.state.empty.description',
      };
    case 'error':
      return {
        titleKey: 'projectOverview.state.error.title',
        descriptionKey: 'projectOverview.state.error.description',
      };
    case 'forbidden':
      return {
        titleKey: 'projectOverview.state.forbidden.title',
        descriptionKey: 'projectOverview.state.forbidden.description',
      };
    case 'unavailable':
      return {
        titleKey: 'projectOverview.state.unavailable.title',
        descriptionKey: 'projectOverview.state.unavailable.description',
      };
    case 'ready':
    case 'degraded':
      return {
        titleKey: 'projectOverview.state.error.title',
        descriptionKey: 'projectOverview.state.error.description',
      };
  }
}

function stateIcon(state: ProjectOverviewPresentationModel['state']) {
  if (state === 'forbidden') return LockClosedIcon;
  if (state === 'loading' || state === 'scope_switch') return ReloadIcon;
  if (state === 'empty') return CubeIcon;
  return ExclamationTriangleIcon;
}
