import React, { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useSearchParams } from 'react-router-dom';

import { Alert, Button, DatePicker, Select, Space, Table, Tag, Typography } from 'antd';

import { eventService, EventLog } from '@/services/eventService';

import { formatDateTime } from '@/utils/date';

const { Title } = Typography;
const { RangePicker } = DatePicker;

export const Events: React.FC = () => {
  const { t } = useTranslation();
  const { tenantId } = useParams<{ tenantId?: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<EventLog[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [types, setTypes] = useState<string[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [typesError, setTypesError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const [page, setPage] = useState(() => {
    const p = Number(searchParams.get('page'));
    return Number.isInteger(p) && p > 0 ? p : 1;
  });
  const [pageSize, setPageSize] = useState(20);
  const [selectedType, setSelectedType] = useState<string | undefined>(
    () => searchParams.get('type') ?? undefined
  );
  const [dateRange, setDateRange] = useState<[string, string] | undefined>();

  // Reflect page/type filters in the URL so views survive reload and sharing
  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    if (page > 1) {
      next.set('page', String(page));
    } else {
      next.delete('page');
    }
    if (selectedType) {
      next.set('type', selectedType);
    } else {
      next.delete('type');
    }
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true });
    }
  }, [page, selectedType, searchParams, setSearchParams]);

  useEffect(() => {
    let isCurrent = true;
    setTypesError(null);

    void eventService
      .getEventTypes(tenantId ? { tenant_id: tenantId } : undefined)
      .then((eventTypes) => {
        if (!isCurrent) return;
        setTypes(eventTypes);
      })
      .catch((err: unknown) => {
        console.error(err);
        if (!isCurrent) return;
        setTypes([]);
        setTypesError(t('events.typesLoadError'));
      });

    return () => {
      isCurrent = false;
    };
  }, [tenantId, t, reloadKey]);

  useEffect(() => {
    let isCurrent = true;

    const fetchEvents = async () => {
      setLoading(true);
      setLoadError(null);
      try {
        const params: Parameters<typeof eventService.listEvents>[0] = { page, page_size: pageSize };
        if (tenantId) params.tenant_id = tenantId;
        if (selectedType) params.event_type = selectedType;
        if (dateRange?.[0]) params.date_from = dateRange[0];
        if (dateRange?.[1]) params.date_to = dateRange[1];
        const res = await eventService.listEvents(params);
        if (!isCurrent) return;
        setData(res.items);
        setTotal(res.total);
      } catch (err) {
        console.error(err);
        if (!isCurrent) return;
        setData([]);
        setTotal(0);
        setLoadError(t('events.loadError'));
      } finally {
        if (isCurrent) {
          setLoading(false);
        }
      }
    };
    void fetchEvents();

    return () => {
      isCurrent = false;
    };
  }, [page, pageSize, selectedType, dateRange, tenantId, t, reloadKey]);

  const handleRetry = () => {
    setReloadKey((key) => key + 1);
  };

  const columns = [
    {
      title: t('events.type'),
      dataIndex: 'event_type',
      key: 'event_type',
      render: (type: string) => <Tag color="blue">{type}</Tag>,
    },
    {
      title: t('events.message'),
      dataIndex: 'message',
      key: 'message',
    },
    {
      title: t('events.source'),
      dataIndex: 'source',
      key: 'source',
      render: (src: string) => <Tag>{src}</Tag>,
    },
    {
      title: t('events.date'),
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date: string) => formatDateTime(date),
    },
  ];

  return (
    <div className="p-6">
      <Title level={4}>{t('events.title')}</Title>

      <Space className="mb-4">
        <Select
          aria-label={t('events.filterByType')}
          allowClear
          placeholder={t('events.filterByType')}
          style={{ width: 200 }}
          value={selectedType}
          onChange={(val: string | undefined) => {
            setSelectedType(val);
            setPage(1);
          }}
          options={types.map((t) => ({ label: t, value: t }))}
        />
        <RangePicker
          aria-label={t('events.filterByDateRange')}
          showTime
          onChange={(dates) => {
            if (dates && dates[0] && dates[1]) {
              setDateRange([dates[0].toISOString(), dates[1].toISOString()]);
            } else {
              setDateRange(undefined);
            }
            setPage(1);
          }}
        />
      </Space>

      {typesError ? (
        <Alert
          title={typesError}
          type="warning"
          showIcon
          className="mb-4"
          action={
            <Button size="small" onClick={handleRetry}>
              {t('common.retry', 'Retry')}
            </Button>
          }
        />
      ) : null}
      {loadError ? (
        <Alert
          title={loadError}
          type="error"
          showIcon
          className="mb-4"
          action={
            <Button size="small" onClick={handleRetry}>
              {t('common.retry', 'Retry')}
            </Button>
          }
        />
      ) : null}

      <Table
        rowKey="id"
        columns={columns}
        dataSource={data}
        loading={loading}
        pagination={{
          current: page,
          pageSize: pageSize,
          total: total,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
        locale={{ emptyText: t('events.noEvents') }}
      />
    </div>
  );
};
