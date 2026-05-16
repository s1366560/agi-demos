import React, { useCallback, useEffect, useState, useMemo } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Table, Input, Tag, Space } from 'antd';
import { Plus, Search as SearchIcon } from 'lucide-react';

import { LazyButton, LazyPopconfirm, LazySelect, useLazyMessage } from '@/components/ui/lazyAntd';

import {
  useInstances,
  useInstanceLoading,
  useInstanceError,
  useInstanceTotal,
  useInstanceActions,
} from '../../stores/instance';

import { getStatusColor, formatDate } from './utils/instanceUtils';

import type { InstanceResponse } from '../../services/instanceService';
import type { ColumnsType } from 'antd/es/table';

const { Search } = Input;

export const InstanceList: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const messageApi = useLazyMessage();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');

  const instances = useInstances();
  const isLoading = useInstanceLoading();
  const error = useInstanceError();
  const total = useInstanceTotal();
  const { listInstances, deleteInstance, restartInstance, clearError, reset } =
    useInstanceActions();

  const runningCount = useMemo(
    () => instances.filter((i) => i.status === 'running').length,
    [instances]
  );
  const stoppedCount = useMemo(
    () => instances.filter((i) => i.status === 'stopped').length,
    [instances]
  );

  const filteredInstances = useMemo(() => {
    return instances.filter((instance) => {
      if (search && !instance.name.toLowerCase().includes(search.toLowerCase())) {
        return false;
      }
      if (statusFilter !== 'all' && instance.status !== statusFilter) {
        return false;
      }
      return true;
    });
  }, [instances, search, statusFilter]);

  useEffect(() => {
    void listInstances();
  }, [listInstances]);

  useEffect(() => {
    return () => {
      clearError();
      reset();
    };
  }, [clearError, reset]);

  useEffect(() => {
    if (error) {
      const displayError = error.length > 200 ? `${error.slice(0, 200)}...` : error;
      messageApi?.error(displayError);
    }
  }, [error, messageApi]);

  const handleCreate = useCallback(() => {
    void navigate('./create');
  }, [navigate]);

  const handleView = useCallback(
    (id: string) => {
      void navigate(`./${id}`);
    },
    [navigate]
  );

  const handleRestart = useCallback(
    async (id: string) => {
      try {
        await restartInstance(id);
        messageApi?.success(t('tenant.instances.restartSuccess'));
      } catch (err) {
        console.error('Failed to restart instance:', err);
        messageApi?.error(t('tenant.instances.restartError', 'Failed to restart instance'));
      }
    },
    [restartInstance, t, messageApi]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteInstance(id);
        messageApi?.success(t('tenant.instances.deleteSuccess'));
      } catch (err) {
        console.error('Failed to delete instance:', err);
        messageApi?.error(t('tenant.instances.deleteError', 'Failed to delete instance'));
      }
    },
    [deleteInstance, t, messageApi]
  );

  const columns: ColumnsType<InstanceResponse> = useMemo(
    () => [
      {
        title: t('tenant.instances.columns.name'),
        dataIndex: 'name',
        key: 'name',
        render: (text: string) => (
          <span className="font-medium text-text-primary dark:text-text-inverse">
            {text || '-'}
          </span>
        ),
      },
      {
        title: t('tenant.instances.columns.status'),
        dataIndex: 'status',
        key: 'status',
        render: (status: string) => (
          <Tag color={getStatusColor(status)}>{t(`tenant.instances.status.${status}`)}</Tag>
        ),
      },
      {
        title: t('tenant.instances.columns.imageVersion'),
        dataIndex: 'image_version',
        key: 'image_version',
      },
      {
        title: t('tenant.instances.columns.replicas'),
        dataIndex: 'replicas',
        key: 'replicas',
        render: (_, record) =>
          `${(record.available_replicas || 0).toString()} / ${record.replicas.toString()}`,
      },
      {
        title: t('tenant.instances.columns.clusterId'),
        dataIndex: 'cluster_id',
        key: 'cluster_id',
        render: (cluster_id: string | null) => cluster_id || '-',
      },
      {
        title: t('tenant.instances.columns.createdAt'),
        dataIndex: 'created_at',
        key: 'created_at',
        render: (date: string) => formatDate(date),
      },
      {
        title: t('tenant.instances.columns.actions'),
        key: 'actions',
        render: (_, record) => (
          <Space size="middle">
            <LazyButton
              type="link"
              onClick={() => {
                handleView(record.id);
              }}
              className="p-0 font-medium"
            >
              {t('tenant.instances.actions.view')}
            </LazyButton>
            <LazyPopconfirm
              title={t('tenant.instances.actions.restartConfirm')}
              onConfirm={() => {
                void handleRestart(record.id);
              }}
              okText={t('common.yes')}
              cancelText={t('common.no')}
            >
              <LazyButton type="link" className="p-0">
                {t('tenant.instances.actions.restart')}
              </LazyButton>
            </LazyPopconfirm>
            <LazyPopconfirm
              title={t('tenant.instances.actions.deleteConfirm')}
              onConfirm={() => {
                void handleDelete(record.id);
              }}
              okText={t('common.yes')}
              cancelText={t('common.no')}
              okButtonProps={{ danger: true }}
            >
              <LazyButton type="link" danger className="p-0">
                {t('tenant.instances.actions.delete')}
              </LazyButton>
            </LazyPopconfirm>
          </Space>
        ),
      },
    ],
    [t, handleView, handleRestart, handleDelete]
  );

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-text-primary dark:text-text-inverse">
            {t('tenant.instances.title')}
          </h1>
          <p className="text-sm text-text-muted mt-1">{t('tenant.instances.subtitle')}</p>
          <section
            aria-label={t('tenant.instances.stats.total')}
            className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-text-secondary dark:text-text-muted"
          >
            <span className="flex items-center gap-1">
              {t('tenant.instances.stats.total')}:{' '}
              <span className="font-semibold text-text-primary dark:text-text-inverse">
                {total}
              </span>
            </span>
            <span className="hidden text-border-light dark:text-border-dark sm:inline">|</span>
            <span className="flex items-center gap-1">
              {t('tenant.instances.stats.running')}:{' '}
              <span className="font-semibold text-success">{runningCount}</span>
            </span>
            <span className="hidden text-border-light dark:text-border-dark sm:inline">|</span>
            <span className="flex items-center gap-1">
              {t('tenant.instances.stats.stopped')}:{' '}
              <span className="font-semibold text-text-muted">{stoppedCount}</span>
            </span>
          </section>
        </div>
        <LazyButton
          type="primary"
          icon={<Plus size={16} aria-hidden="true" />}
          onClick={handleCreate}
          aria-label={t('tenant.instances.createNew')}
          className="inline-flex items-center justify-center"
        >
          {t('tenant.instances.createNew')}
        </LazyButton>
      </div>

      <div className="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark transition-colors duration-200">
        <div className="p-4 border-b border-border-light dark:border-border-dark">
          <div className="grid w-full grid-cols-1 gap-3 sm:grid-cols-[minmax(0,300px)_150px]">
            <Search
              placeholder={t('tenant.instances.searchPlaceholder')}
              aria-label={t('tenant.instances.searchPlaceholder')}
              allowClear
              enterButton={
                <>
                  <span className="sr-only">{t('common.search', 'Search')}</span>
                  <SearchIcon size={16} aria-hidden="true" />
                </>
              }
              onSearch={setSearch}
              onChange={(e) => {
                setSearch(e.target.value);
              }}
              className="w-full"
              style={{ width: '100%' }}
            />
            <LazySelect
              aria-label={t('tenant.instances.status.all')}
              value={statusFilter}
              onChange={setStatusFilter}
              className="w-full"
              style={{ width: '100%' }}
              options={[
                { value: 'all', label: t('tenant.instances.status.all') },
                { value: 'provisioning', label: t('tenant.instances.status.provisioning') },
                { value: 'running', label: t('tenant.instances.status.running') },
                { value: 'stopped', label: t('tenant.instances.status.stopped') },
                { value: 'error', label: t('tenant.instances.status.error') },
                { value: 'terminated', label: t('tenant.instances.status.terminated') },
              ]}
            />
          </div>
        </div>

        <Table
          columns={columns}
          dataSource={filteredInstances}
          rowKey="id"
          loading={isLoading}
          scroll={{ x: 'max-content' }}
          className="max-w-full"
          locale={{ emptyText: t('tenant.instances.emptyText', 'No instances found') }}
          pagination={{
            pageSize: 10,
            showSizeChanger: true,
            showTotal: (total) => t('common.pagination.total', { total }),
          }}
        />
      </div>
    </div>
  );
};
