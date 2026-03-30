import React, { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Table, Select, DatePicker, Typography, Space, Tag } from 'antd';

import { eventService, EventLog } from '@/services/eventService';

const { Title } = Typography;
const { RangePicker } = DatePicker;

export const Events: React.FC = () => {
  const { t } = useTranslation();
  const [data, setData] = useState<EventLog[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [types, setTypes] = useState<string[]>([]);

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selectedType, setSelectedType] = useState<string | undefined>();
  const [dateRange, setDateRange] = useState<[string, string] | undefined>();

  useEffect(() => {
    eventService.getEventTypes().then(setTypes).catch(console.error);
  }, []);

  useEffect(() => {
    const fetchEvents = async () => {
      setLoading(true);
      try {
        const params: any = { page, page_size: pageSize };
        if (selectedType) params.event_type = selectedType;
        if (dateRange?.[0]) params.date_from = dateRange[0];
        if (dateRange?.[1]) params.date_to = dateRange[1];
        const res = await eventService.listEvents(params);
        setData(res.items);
        setTotal(res.total);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    };
    fetchEvents();
  }, [page, pageSize, selectedType, dateRange]);

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
      render: (date: string) => new Date(date).toLocaleString(),
    },
  ];

  return (
    <div style={{ padding: '24px' }}>
      <Title level={4}>{t('events.title')}</Title>

      <Space style={{ marginBottom: 16 }}>
        <Select
          allowClear
          placeholder={t('events.filterByType')}
          style={{ width: 200 }}
          onChange={(val) => {
            setSelectedType(val);
            setPage(1);
          }}
          options={types.map((t) => ({ label: t, value: t }))}
        />
        <RangePicker
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
