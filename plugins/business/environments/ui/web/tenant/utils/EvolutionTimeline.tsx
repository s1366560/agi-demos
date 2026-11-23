import { useTranslation } from 'react-i18next';

import { Badge, Tag, Timeline, Typography } from 'antd';

import type { EvolutionEventResponse } from '@/services/geneMarketService';

import { formatDateTime } from '@/utils/date';

import { getEventColor, getEventTypeLabel, getStatusBadge } from './evolutionUtils';

const { Text } = Typography;

interface EvolutionTimelineProps {
  events: EvolutionEventResponse[];
  /** Show the event status badge (used by the instance-scoped EvolutionLog). */
  showStatus?: boolean;
  /** Localized label rendered before the trigger, e.g. t('tenant.evolution.trigger'). */
  triggerLabel: string;
}

/** Shared evolution-event timeline used by EvolutionLog and GeneDetail. */
export const EvolutionTimeline: React.FC<EvolutionTimelineProps> = ({
  events,
  showStatus = false,
  triggerLabel,
}) => {
  const { t } = useTranslation();
  return (
    <Timeline
      items={events.map((evt) => ({
        color: getEventColor(evt.event_type),
        content: (
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <Tag color={getEventColor(evt.event_type)}>
                {getEventTypeLabel(t, evt.event_type)}
              </Tag>
              {showStatus ? <Badge status={getStatusBadge(evt.status)} text={evt.status} /> : null}
              <Text type="secondary" className="text-xs">
                {formatDateTime(evt.created_at)}
              </Text>
            </div>
            {(evt.gene_name || evt.gene_slug) && (
              <Text className="text-sm">{evt.gene_name || evt.gene_slug}</Text>
            )}
            {(evt.from_version || evt.to_version) && (
              <Text className="text-sm">
                {evt.from_version ?? 'none'} → {evt.to_version ?? 'none'}
              </Text>
            )}
            {evt.trigger && (
              <Text type="secondary" className="text-sm">
                {triggerLabel}: {evt.trigger}
              </Text>
            )}
          </div>
        ),
      }))}
    />
  );
};
