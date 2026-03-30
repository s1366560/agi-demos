import React, { useEffect, useState, useCallback } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useNavigate } from 'react-router-dom';

import {
  Timeline,
  Button,
  Badge,
  Card,
  Typography,
  Spin,
  Alert,
  Pagination,
  Select,
  Tag,
  Empty,
} from 'antd';
import { ArrowLeft } from 'lucide-react';

import {
  useEvolutionEvents,
  useGeneMarketLoading,
  useGeneMarketError,
  useGeneMarketActions,
} from '../../stores/geneMarket';

const { Title, Text } = Typography;

const EVENT_TYPE_COLORS: Record<string, string> = {
  installed: 'green',
  uninstalled: 'red',
  upgraded: 'blue',
  downgraded: 'orange',
  config_changed: 'purple',
  error: 'red',
};

const getEventColor = (eventType: string): string => {
  return EVENT_TYPE_COLORS[eventType] ?? 'default';
};

export const EvolutionLog: React.FC = () => {
  const { t } = useTranslation();
  const { instanceId } = useParams();
  const navigate = useNavigate();

  const evolutionEvents = useEvolutionEvents();
  const loading = useGeneMarketLoading();
  const error = useGeneMarketError();
  const { listEvolutionEvents, clearError } = useGeneMarketActions();

  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [eventTypeFilter, setEventTypeFilter] = useState<string | undefined>(undefined);

  const fetchEvents = useCallback(() => {
    if (!instanceId) return;
    const params: Record<string, unknown> = { page, page_size: pageSize };
    if (eventTypeFilter) {
      params.event_type = eventTypeFilter;
    }
    listEvolutionEvents(instanceId, params).catch(() => {});
  }, [instanceId, page, pageSize, eventTypeFilter, listEvolutionEvents]);

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
      <Alert type="warning" message={t('tenant.evolution.noInstance', 'No instance selected')} />
    );
  }

  return (
    <div className="max-w-4xl mx-auto w-full flex flex-col gap-6">
      <div className="flex items-center gap-4">
        <Button icon={<ArrowLeft size={16} />} onClick={() => navigate(-1)}>
          {t('common.back', 'Back')}
        </Button>
        <Title level={3} className="!mb-0">
          {t('tenant.evolution.title', 'Evolution Log')}
        </Title>
      </div>

      <div className="flex items-center gap-4">
        <Select
          allowClear
          placeholder={t('tenant.evolution.filterByType', 'Filter by event type')}
          value={eventTypeFilter}
          onChange={(val) => {
            setEventTypeFilter(val);
            setPage(1);
          }}
          className="w-48"
          options={[
            { label: t('tenant.evolution.types.installed', 'Installed'), value: 'installed' },
            { label: t('tenant.evolution.types.uninstalled', 'Uninstalled'), value: 'uninstalled' },
            { label: t('tenant.evolution.types.upgraded', 'Upgraded'), value: 'upgraded' },
            { label: t('tenant.evolution.types.downgraded', 'Downgraded'), value: 'downgraded' },
            {
              label: t('tenant.evolution.types.configChanged', 'Config Changed'),
              value: 'config_changed',
            },
            { label: t('tenant.evolution.types.error', 'Error'), value: 'error' },
          ]}
        />
      </div>

      {error && <Alert type="error" message={error} closable onClose={clearError} />}

      {loading && evolutionEvents.length === 0 ? (
        <div className="flex justify-center p-12">
          <Spin size="large" />
        </div>
      ) : evolutionEvents.length === 0 ? (
        <Card>
          <Empty description={t('tenant.evolution.empty', 'No evolution events found')} />
        </Card>
      ) : (
        <>
          <Card className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
            <Timeline
              items={evolutionEvents.map((evt) => ({
                color: getEventColor(evt.event_type),
                children: (
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                      <Tag color={getEventColor(evt.event_type)}>{evt.event_type}</Tag>
                      <Badge
                        status={evt.status === 'success' ? 'success' : 'error'}
                        text={evt.status}
                      />
                    </div>
                    <Text type="secondary" className="text-xs">
                      {new Date(evt.created_at).toLocaleString()}
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
              total={evolutionEvents.length < pageSize ? page * pageSize : (page + 1) * pageSize}
              onChange={handlePageChange}
              showSizeChanger={false}
            />
          </div>
        </>
      )}
    </div>
  );
};
