import React, { useCallback, useEffect, useState, useMemo } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Table, Input, Tag, Button, Space, Popconfirm, Select, message } from 'antd';
import { CircleStop, PlayCircle, Plus, Server } from 'lucide-react';

import {
  useInstances,
  useInstanceLoading,
  useInstanceError,
  useInstanceTotal,
  useInstanceActions,
} from '../../stores/instance';

import type { InstanceResponse } from '../../services/instanceService';
import type { ColumnsType } from 'antd/es/table';

const { Search } = Input;
const { Option } = Select;

export const InstanceList: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
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
    listInstances();
  }, [listInstances]);

  useEffect(() => {
    return () => {
      clearError();
      reset();
    };
  }, [clearError, reset]);

  useEffect(() => {
    if (error) {
      message.error(error);
    }
  }, [error]);

  const handleCreate = useCallback(() => {
    navigate('./create');
  }, [navigate]);

  const handleView = useCallback(
    (id: string) => {
      navigate(`./${id}`);
    },
    [navigate]
  );

  const handleRestart = useCallback(
    async (id: string) => {
      try {
        await restartInstance(id);
        message.success(t('tenant.instances.restartSuccess'));
      } catch (_err) { /* ignore */ }
    },
    [restartInstance, t]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteInstance(id);
        message.success(t('tenant.instances.deleteSuccess'));
      } catch (_err) { /* ignore */ }
    },
    [deleteInstance, t]
  );

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'provisioning':
        return 'blue';
      case 'running':
        return 'green';
      case 'stopped':
        return 'default';
      case 'error':
        return 'red';
      case 'terminated':
        return 'gray';
      default:
        return 'default';
    }
  };

  const columns: ColumnsType<InstanceResponse> = [
    {
      title: t('tenant.instances.columns.name'),
      dataIndex: 'name',
      key: 'name',
      render: (text: string) => (
        <span className="font-medium text-slate-900 dark:text-slate-100">{text}</span>
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
      render: (_, record) => `${record.available_replicas || 0} / ${record.replicas}`,
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
      render: (date: string) => new Date(date).toLocaleString(),
    },
    {
      title: t('tenant.instances.columns.actions'),
      key: 'actions',
      render: (_, record) => (
        <Space size="middle">
          <Button
            type="link"
            onClick={() => {
              handleView(record.id);
            }}
            className="p-0"
          >
            {t('tenant.instances.actions.view')}
          </Button>
          <Popconfirm
            title={t('tenant.instances.actions.restartConfirm')}
            onConfirm={() => handleRestart(record.id)}
            okText={t('common.yes')}
            cancelText={t('common.no')}
          >
            <Button type="link" className="p-0">
              {t('tenant.instances.actions.restart')}
            </Button>
          </Popconfirm>
          <Popconfirm
            title={t('tenant.instances.actions.deleteConfirm')}
            onConfirm={() => handleDelete(record.id)}
            okText={t('common.yes')}
            cancelText={t('common.no')}
            okButtonProps={{ danger: true }}
          >
            <Button type="link" danger className="p-0">
              {t('tenant.instances.actions.delete')}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-8">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            {t('tenant.instances.title')}
          </h1>
          <p className="text-sm text-slate-500 mt-1">{t('tenant.instances.subtitle')}</p>
        </div>
        <button
          type="button"
          onClick={handleCreate}
          className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors"
        >
          <Plus size={16} />
          {t('tenant.instances.createNew')}
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {t('tenant.instances.stats.total')}
              </p>
              <p className="text-2xl font-bold text-slate-900 dark:text-white mt-1">{total}</p>
            </div>
            <Server size={16} className="text-4xl text-primary-500" />
          </div>
        </div>

        <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {t('tenant.instances.stats.running')}
              </p>
              <p className="text-2xl font-bold text-green-600 dark:text-green-400 mt-1">
                {runningCount}
              </p>
            </div>
            <PlayCircle size={16} className="text-4xl text-green-500" />
          </div>
        </div>

        <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {t('tenant.instances.stats.stopped')}
              </p>
              <p className="text-2xl font-bold text-slate-600 dark:text-slate-400 mt-1">
                {stoppedCount}
              </p>
            </div>
            <CircleStop size={16} className="text-4xl text-slate-500" />
          </div>
        </div>
      </div>

      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
        <div className="p-4 border-b border-slate-200 dark:border-slate-700 flex flex-col sm:flex-row gap-4 justify-between items-center">
          <Space>
            <Search
              placeholder={t('tenant.instances.searchPlaceholder')}
              allowClear
              onSearch={setSearch}
              onChange={(e) => {
                setSearch(e.target.value);
              }}
              style={{ width: 300 }}
            />
            <Select value={statusFilter} onChange={setStatusFilter} style={{ width: 150 }}>
              <Option value="all">{t('tenant.instances.status.all')}</Option>
              <Option value="provisioning">{t('tenant.instances.status.provisioning')}</Option>
              <Option value="running">{t('tenant.instances.status.running')}</Option>
              <Option value="stopped">{t('tenant.instances.status.stopped')}</Option>
              <Option value="error">{t('tenant.instances.status.error')}</Option>
              <Option value="terminated">{t('tenant.instances.status.terminated')}</Option>
            </Select>
          </Space>
        </div>

        <Table
          columns={columns}
          dataSource={filteredInstances}
          rowKey="id"
          loading={isLoading}
          pagination={{
            pageSize: 10,
            showSizeChanger: true,
            showTotal: (total) => t('common.pagination.total', { total }),
          }}
          className="w-full overflow-x-auto"
        />
      </div>
    </div>
  );
};
