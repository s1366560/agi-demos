import React, { useEffect, useState, useCallback } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useNavigate } from 'react-router-dom';

import { Card, Typography, Alert, Pagination } from 'antd';
import { ArrowLeft } from 'lucide-react';

import { logger } from '@/utils/logger';

import { LazyButton, LazySpin, LazyEmpty, LazySelect } from '@/components/ui/lazyAntd';

import {
  useEvolutionEvents,
  useEvolutionTotal,
  useGeneMarketLoading,
  useGeneMarketError,
  useGeneMarketActions,
} from '../../stores/geneMarket';

import { EvolutionTimeline } from './utils/EvolutionTimeline';
import { EVENT_TYPE_OPTIONS, getEventTypeLabel } from './utils/evolutionUtils';

import type {
  EvolutionEventListParams,
  EvolutionEventType,
} from '../../services/geneMarketService';

const { Title } = Typography;

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
      logger.error('Failed to list evolution events:', err);
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

      {error && (
        <Alert
          type="error"
          title={error}
          closable={{ onClose: clearError }}
          action={
            <LazyButton
              size="small"
              onClick={() => {
                fetchEvents();
              }}
            >
              {t('common.retry', 'Retry')}
            </LazyButton>
          }
        />
      )}

      {loading && evolutionEvents.length === 0 ? (
        <div className="flex justify-center p-12">
          <LazySpin size="large" />
        </div>
      ) : evolutionEvents.length === 0 && error ? null : evolutionEvents.length === 0 ? (
        <Card>
          <LazyEmpty description={t('tenant.evolution.empty', 'No evolution events found')} />
        </Card>
      ) : (
        <>
          <Card className="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark">
            <EvolutionTimeline
              events={evolutionEvents}
              showStatus
              triggerLabel={t('tenant.evolution.trigger', 'Trigger')}
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
