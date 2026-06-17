import React, { useEffect, useState, useCallback } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useNavigate } from 'react-router-dom';

import { Timeline, Badge, Card, Typography, Alert, Pagination, Tag } from 'antd';
import { ArrowLeft } from 'lucide-react';

import { LazyButton, LazySpin, LazyEmpty, LazySelect } from '@/components/ui/lazyAntd';

import {
  useEvolutionEvents,
  useEvolutionTotal,
  useGeneMarketLoading,
  useGeneMarketError,
  useGeneMarketActions,
} from '../../stores/geneMarket';

import { formatDate } from './utils/instanceUtils';

import type {
  EvolutionEventListParams,
  EvolutionEventType,
} from '../../services/geneMarketService';
import type { TFunction } from 'i18next';

const { Title, Text } = Typography;

const EVENT_TYPE_COLORS: Record<string, string> = {
  learned: 'green',
  forgot: 'red',
  upgraded: 'blue',
  created_variant: 'purple',
  installed_genome: 'cyan',
  uninstalled_genome: 'orange',
  simplified: 'geekblue',
};

const EVENT_TYPE_OPTIONS: EvolutionEventType[] = [
  'learned',
  'forgot',
  'upgraded',
  'created_variant',
  'installed_genome',
  'uninstalled_genome',
  'simplified',
];

const getEventColor = (eventType: string): string => {
  return EVENT_TYPE_COLORS[eventType] ?? 'default';
};

const getEventTypeLabel = (t: TFunction, type: string) => {
  return t(`tenant.evolution.types.${type}`, type);
};

const getStatusBadge = (status: string): 'success' | 'error' | 'processing' | 'default' => {
  if (status === 'completed' || status === 'success') return 'success';
  if (status === 'pending' || status === 'running') return 'processing';
  if (status === 'failed' || status === 'error') return 'error';
  return 'default';
};

export const EvolutionLog: React.FC = () => {
  const { t } = useTranslation();
  const { tenantId, instanceId } = useParams<{ tenantId?: string; instanceId?: string }>();
  const navigate = useNavigate();

  const evolutionEvents = useEvolutionEvents();
  const evolutionTotal = useEvolutionTotal();
  const loading = useGeneMarketLoading();
  const error = useGeneMarketError();
  const { listEvolutionEvents, clearError } = useGeneMarketActions();

  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [eventTypeFilter, setEventTypeFilter] = useState<EvolutionEventType | undefined>(undefined);

  const fetchEvents = useCallback(() => {
    if (!instanceId) return;
    const params: EvolutionEventListParams = { page, page_size: pageSize };
    if (tenantId) {
      params.tenant_id = tenantId;
    }
    if (eventTypeFilter) {
      params.event_type = eventTypeFilter;
    }
    listEvolutionEvents(instanceId, params).catch((err: unknown) => {
      console.error('Failed to list evolution events:', err);
    });
  }, [instanceId, page, pageSize, eventTypeFilter, listEvolutionEvents, tenantId]);

  useEffect(() => {
    fetchEvents();
    return () => {
      clearError();
    };
  }, [fetchEvents, clearError]);

  const handlePageChange = (newPage: number) => {
    setPage(newPage);
  };

  if (!instanceId) {
    return (
      <Alert type="warning" title={t('tenant.evolution.noInstance', 'No instance selected')} />
    );
  }

  return (
    <div className="max-w-4xl mx-auto w-full flex flex-col gap-6">
      <div className="flex items-center gap-4">
        <LazyButton icon={<ArrowLeft size={16} />} onClick={() => navigate(-1)}>
          {t('common.back', 'Back')}
        </LazyButton>
        <Title level={3} className="!mb-0">
          {t('tenant.evolution.title', 'Evolution Log')}
        </Title>
      </div>

      <div className="flex items-center gap-4">
        <LazySelect
          allowClear
          placeholder={t('tenant.evolution.filterByType', 'Filter by event type')}
          value={eventTypeFilter}
          onChange={(val: string | undefined) => {
            setEventTypeFilter(val as EvolutionEventType | undefined);
            setPage(1);
          }}
          className="w-48"
          options={EVENT_TYPE_OPTIONS.map((value) => ({
            label: getEventTypeLabel(t, value),
            value,
          }))}
        />
      </div>

      {error && <Alert type="error" title={error} closable={{ onClose: clearError }} />}

      {loading && evolutionEvents.length === 0 ? (
        <div className="flex justify-center p-12">
          <LazySpin size="large" />
        </div>
      ) : evolutionEvents.length === 0 ? (
        <Card>
          <LazyEmpty description={t('tenant.evolution.empty', 'No evolution events found')} />
        </Card>
      ) : (
        <>
          <Card className="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark">
            <Timeline
              items={evolutionEvents.map((evt) => ({
                color: getEventColor(evt.event_type),
                content: (
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                      <Tag color={getEventColor(evt.event_type)}>
                        {getEventTypeLabel(t, evt.event_type)}
                      </Tag>
                      <Badge status={getStatusBadge(evt.status)} text={evt.status} />
                    </div>
                    {(evt.gene_name || evt.gene_slug) && (
                      <Text className="text-sm">{evt.gene_name || evt.gene_slug}</Text>
                    )}
                    <Text type="secondary" className="text-xs">
                      {formatDate(evt.created_at)}
                    </Text>
                    {evt.from_version && evt.to_version && (
                      <Text className="text-sm">
                        {evt.from_version} → {evt.to_version}
                      </Text>
                    )}
                    {evt.trigger && (
                      <Text type="secondary" className="text-sm">
                        {t('tenant.evolution.trigger', 'Trigger')}: {evt.trigger}
                      </Text>
                    )}
                  </div>
                ),
              }))}
            />
          </Card>

          <div className="flex justify-center">
            <Pagination
              current={page}
              pageSize={pageSize}
              total={evolutionTotal}
              onChange={handlePageChange}
              showSizeChanger={false}
            />
          </div>
        </>
      )}
    </div>
  );
};
