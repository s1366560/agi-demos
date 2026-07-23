import React, { useCallback, useEffect, useState, useMemo } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { Table, Input, Tag, Space } from 'antd';
import { Plus, RefreshCw, Search as SearchIcon } from 'lucide-react';

import { SkeletonLoader } from '@/components/common/SkeletonLoader';
import {
  LazyAlert,
  LazyButton,
  LazyPopconfirm,
  LazySelect,
  useLazyMessage,
} from '@/components/ui/lazyAntd';

import { useDebounce } from '../../hooks/useDebounce';
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

const PAGE_SIZE = 20;

export const InstanceList: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const messageApi = useLazyMessage();
  // Restore search/status/page from the URL so shared or reloaded links keep the view
  const [search, setSearch] = useState(searchParams.get('search') ?? '');
  const [statusFilter, setStatusFilter] = useState<string>(searchParams.get('status') ?? 'all');
  const [page, setPage] = useState(() => {
    const pageParam = Number(searchParams.get('page'));
    return Number.isInteger(pageParam) && pageParam > 0 ? pageParam : 1;
  });

  // Debounce search and filter server-side so results cover all pages
  const debouncedSearch = useDebounce(search, 400);

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

  const loadPage = useCallback(
    (nextPage: number) => {
      return listInstances({
        page: nextPage,
        page_size: PAGE_SIZE,
        ...(debouncedSearch ? { search: debouncedSearch } : {}),
        ...(statusFilter !== 'all' ? { status: statusFilter } : {}),
      });
    },
    [listInstances, debouncedSearch, statusFilter]
  );

  useEffect(() => {
    void loadPage(page);
  }, [loadPage, page]);

  // Reflect search/status/page in the URL so views survive reload and sharing
  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    if (page > 1) {
      next.set('page', String(page));
    } else {
      next.delete('page');
    }
    if (search) {
      next.set('search', search);
    } else {
      next.delete('search');
    }
    if (statusFilter !== 'all') {
      next.set('status', statusFilter);
    } else {
      next.delete('status');
    }
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true });
    }
  }, [page, search, statusFilter, searchParams, setSearchParams]);

  useEffect(() => {
    return () => {
      clearError();
      reset();
    };
  }, [clearError, reset]);

  useEffect(() => {
    if (error) {
      const displayError = error.length > 200 ? `${error.slice(0, 200)}…` : error;
      messageApi?.error(displayError);
    }
  }, [error, messageApi]);

  const handlePageChange = useCallback((nextPage: number) => {
    setPage(nextPage);
  }, []);

  const handleSearchChange = useCallback((value: string) => {
    setPage(1);
    setSearch(value);
  }, []);

  const handleStatusFilterChange = useCallback((value: string) => {
    setPage(1);
    setStatusFilter(value);
  }, []);

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

  const renderPaginationItem = useCallback(
    (_page: number, type: string, originalElement: React.ReactNode) => {
      const label =
        type === 'prev'
          ? t('tenant.instances.pagination.previousPage')
          : type === 'next'
            ? t('tenant.instances.pagination.nextPage')
            : undefined;

      if (!label || !React.isValidElement(originalElement)) {
        return originalElement;
      }

      return React.cloneElement(originalElement, {
        'aria-label': label,
        title: label,
      } as React.AriaAttributes & { title: string });
    },
    [t]
  );

  const tablePagination = useMemo(
    () => ({
      current: page,
      pageSize: PAGE_SIZE,
      total,
      showSizeChanger: false,
      showTotal: (nextTotal: number) => t('common.pagination.total', { total: nextTotal }),
      itemRender: renderPaginationItem,
      onChange: handlePageChange,
    }),
    [page, total, renderPaginationItem, handlePageChange, t]
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
        render: (_, record) => {
          const instanceName = record.name || record.id;

          return (
            <Space size="middle">
              <LazyButton
                type="link"
                onClick={() => {
                  handleView(record.id);
                }}
                aria-label={t('tenant.instances.actions.viewInstance', { name: instanceName })}
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
                <LazyButton
                  type="link"
                  className="p-0"
                  aria-label={t('tenant.instances.actions.restartInstance', {
                    name: instanceName,
                  })}
                >
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
                <LazyButton
                  type="link"
                  danger
                  className="p-0"
                  aria-label={t('tenant.instances.actions.deleteInstance', {
                    name: instanceName,
                  })}
                >
                  {t('tenant.instances.actions.delete')}
                </LazyButton>
              </LazyPopconfirm>
            </Space>
          );
        },
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
              <span className="text-xs">{t('tenant.instances.stats.pageNote', '(this page)')}</span>
            </span>
            <span className="hidden text-border-light dark:text-border-dark sm:inline">|</span>
            <span className="flex items-center gap-1">
              {t('tenant.instances.stats.stopped')}:{' '}
              <span className="font-semibold text-text-muted">{stoppedCount}</span>
              <span className="text-xs">{t('tenant.instances.stats.pageNote', '(this page)')}</span>
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
              value={search}
              allowClear
              enterButton={
                <>
                  <span className="sr-only">{t('common.search', 'Search')}</span>
                  <SearchIcon size={16} aria-hidden="true" />
                </>
              }
              onSearch={handleSearchChange}
              onChange={(e) => {
                handleSearchChange(e.target.value);
              }}
              className="w-full"
              style={{ width: '100%' }}
            />
            <LazySelect
              aria-label={t('tenant.instances.status.all')}
              value={statusFilter}
              onChange={handleStatusFilterChange}
              className="w-full"
              style={{ width: '100%' }}
              options={[
                { value: 'all', label: t('tenant.instances.status.all') },
                { value: 'creating', label: t('tenant.instances.status.creating') },
                { value: 'deploying', label: t('tenant.instances.status.deploying') },
                { value: 'running', label: t('tenant.instances.status.running') },
                { value: 'stopped', label: t('tenant.instances.status.stopped') },
                { value: 'restarting', label: t('tenant.instances.status.restarting') },
                { value: 'scaling', label: t('tenant.instances.status.scaling') },
                { value: 'learning', label: t('tenant.instances.status.learning') },
                { value: 'error', label: t('tenant.instances.status.error') },
                { value: 'deleting', label: t('tenant.instances.status.deleting') },
              ]}
            />
          </div>
        </div>

        {error && (
          <div className="border-b border-border-light p-4 dark:border-border-dark">
            <LazyAlert
              type="error"
              showIcon
              message={t('tenant.instances.loadFailed', 'Failed to load instances')}
              description={error}
              action={
                <button
                  type="button"
                  onClick={() => {
                    clearError();
                    void loadPage(page);
                  }}
                  className="inline-flex items-center justify-center gap-1 rounded-md border border-red-300 px-3 py-1 text-sm font-medium text-red-700 transition-colors hover:bg-red-50 dark:border-red-700 dark:text-red-300 dark:hover:bg-red-950/30"
                >
                  <RefreshCw size={14} />
                  {t('common.retry', 'Retry')}
                </button>
              }
            />
          </div>
        )}

        {isLoading && instances.length === 0 ? (
          <SkeletonLoader type="table" rows={8} />
        ) : (
          <Table
            columns={columns}
            dataSource={instances}
            rowKey="id"
            loading={isLoading}
            scroll={{ x: 'max-content' }}
            className="max-w-full"
            locale={{ emptyText: t('tenant.instances.emptyText', 'No instances found') }}
            pagination={tablePagination}
          />
        )}
      </div>
    </div>
  );
};
