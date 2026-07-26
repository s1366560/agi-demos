import { useMemo, useState } from 'react';
import {
  ChevronRightIcon,
  ExternalLinkIcon,
  FileTextIcon,
  GlobeIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { AgentTimelineItem } from '../../types';
import type {
  AggregatedToolSource,
  AggregatedToolSourceGroup,
} from './toolSourceAggregationModel';
import { aggregateStructuredToolSources } from './toolSourceAggregationModel';

export function AggregatedSourcesCard({ items }: { items: readonly AgentTimelineItem[] }) {
  const { t } = useI18n();
  const aggregation = useMemo(() => aggregateStructuredToolSources(items), [items]);
  if (!aggregation) return null;

  return (
    <section className="aggregated-sources-card" data-testid="aggregated-sources-card">
      <header className="aggregated-sources-header">
        <span className="aggregated-sources-title">
          <GlobeIcon aria-hidden="true" />
          <strong>{t('chat.aggregatedSources.title')}</strong>
        </span>
        <span className="aggregated-sources-metrics">
          {t('chat.aggregatedSources.metrics', {
            sources: aggregation.sourceCount,
            calls: aggregation.callCount,
            groups: aggregation.groups.length,
          })}
        </span>
      </header>
      <div className="aggregated-sources-groups">
        {aggregation.groups.map((group, index) => (
          <AggregatedSourceGroup
            group={group}
            initiallyOpen={index < 2}
            key={group.key}
          />
        ))}
      </div>
    </section>
  );
}

function AggregatedSourceGroup({
  group,
  initiallyOpen,
}: {
  group: AggregatedToolSourceGroup;
  initiallyOpen: boolean;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(initiallyOpen);
  const label = group.label ?? t('chat.aggregatedSources.other');
  return (
    <details
      className="aggregated-source-group"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary aria-label={t('chat.aggregatedSources.group', { group: label })}>
        <ChevronRightIcon aria-hidden="true" />
        <span>{label}</span>
        <em>{group.sources.length}</em>
      </summary>
      <ul>
        {group.sources.map((source) => (
          <AggregatedSourceRow source={source} key={source.id} />
        ))}
      </ul>
    </details>
  );
}

function AggregatedSourceRow({ source }: { source: AggregatedToolSource }) {
  const { t } = useI18n();
  const icon = source.url ? <GlobeIcon /> : <FileTextIcon />;
  return (
    <li className="aggregated-source-row">
      <span className="aggregated-source-icon" aria-hidden="true">
        {icon}
      </span>
      <span className="aggregated-source-copy">
        {source.url ? (
          <a
            href={source.url}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={t('chat.aggregatedSources.open', { title: source.title })}
          >
            <span>{source.title}</span>
            <ExternalLinkIcon aria-hidden="true" />
          </a>
        ) : (
          <strong>{source.title}</strong>
        )}
        {source.snippet ? <small>{source.snippet}</small> : null}
      </span>
      {source.score !== undefined ? (
        <em className="aggregated-source-score">
          {t('chat.aggregatedSources.score', { score: source.score.toFixed(2) })}
        </em>
      ) : null}
    </li>
  );
}
