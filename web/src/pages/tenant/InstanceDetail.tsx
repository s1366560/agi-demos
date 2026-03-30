import React, { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useNavigate } from 'react-router-dom';

import { Table, Tag, Button, Space, Popconfirm, message, Card, Modal, InputNumber } from 'antd';
import {
  ArrowLeft,
  FileText,
  Network,
  Users,
  Dna,
  Settings,
  LayoutDashboard,
} from 'lucide-react';

import {
  useCurrentInstance,
  useInstanceMembers,
  useInstanceConfig,
  useInstanceLoading,
  useInstanceActions,
  useInstanceStore,
} from '../../stores/instance';

import type { InstanceMemberResponse } from '../../services/instanceService';
import type { ColumnsType } from 'antd/es/table';

export const InstanceDetail: React.FC = () => {
  const { instanceId: id } = useParams<{ instanceId: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const [scaleModalVisible, setScaleModalVisible] = useState(false);
  const [newReplicas, setNewReplicas] = useState<number>(1);

  const instance = useCurrentInstance();
  const members = useInstanceMembers();
  const config = useInstanceConfig();
  const isLoading = useInstanceLoading();
  const { getInstance, restartInstance, deleteInstance, scaleInstance } = useInstanceActions();
  const listMembers = useInstanceStore((s) => s.listMembers);

  useEffect(() => {
    if (id) {
      getInstance(id);
      listMembers(id);
    }
  }, [id, getInstance, listMembers]);

  const handleBack = () => {
    navigate('..');
  };

  const handleRestart = async () => {
    if (!id) return;
    try {
      await restartInstance(id);
      message.success(t('tenant.instances.restartSuccess'));
    } catch {
      // Error already handled by service
    }
  };

  const handleDelete = async () => {
    if (!id) return;
    try {
      await deleteInstance(id);
      message.success(t('tenant.instances.deleteSuccess'));
      navigate('..');
    } catch {
      // Error already handled by service
    }
  };

  const handleScale = async () => {
    if (!id) return;
    try {
      await scaleInstance(id, newReplicas);
      message.success(t('tenant.instances.scaleSuccess'));
      setScaleModalVisible(false);
    } catch {
      // Error already handled by service
    }
  };

  const handleCopyToken = () => {
    if (instance?.proxy_token) {
      navigator.clipboard.writeText(instance.proxy_token);
      message.success(t('tenant.instances.tokenCopied'));
    }
  };

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

  const memberColumns: ColumnsType<InstanceMemberResponse> = [
    {
      title: t('tenant.instances.columns.userId'),
      dataIndex: 'user_id',
      key: 'user_id',
    },
    {
      title: t('tenant.instances.columns.role'),
      dataIndex: 'role',
      key: 'role',
      render: (role: string) => <Tag color={role === 'admin' ? 'blue' : 'default'}>{role}</Tag>,
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
      render: () => (
        <Button type="link" danger className="p-0">
          {t('tenant.instances.actions.removeMember')}
        </Button>
      ),
    },
  ];

  if (!instance) {
    return (
      <div className="p-8 text-center">
        {isLoading ? t('common.loading') : t('common.notFound')}
      </div>
    );
  }

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-8">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <Button
            type="text"
            icon={<ArrowLeft size={16} />}
            onClick={handleBack}
          />
          <div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-white flex items-center gap-3">
              {instance.name}
              <Tag color={getStatusColor(instance.status)} className="m-0">
                {t(`tenant.instances.status.${instance.status}`)}
              </Tag>
            </h1>
            <p className="text-sm text-slate-500 mt-1">ID: {instance.id}</p>
          </div>
        </div>
        <Space>
          <Button
            onClick={() => {
              setNewReplicas(instance.replicas);
              setScaleModalVisible(true);
            }}
          >
            {t('tenant.instances.actions.scale')}
          </Button>
          <Popconfirm
            title={t('tenant.instances.actions.restartConfirm')}
            onConfirm={handleRestart}
            okText={t('common.yes')}
            cancelText={t('common.no')}
          >
            <Button>{t('tenant.instances.actions.restart')}</Button>
          </Popconfirm>
          <Popconfirm
            title={t('tenant.instances.actions.deleteConfirm')}
            onConfirm={handleDelete}
            okText={t('common.yes')}
            cancelText={t('common.no')}
            okButtonProps={{ danger: true }}
          >
            <Button danger>{t('tenant.instances.actions.delete')}</Button>
          </Popconfirm>
        </Space>
      </div>

      <div className="flex items-center gap-1 border-b border-slate-200 dark:border-slate-700 -mb-2">
        {[
          {
            key: 'overview',
            label: t('tenant.instances.tabs.overview'),
            icon: <LayoutDashboard size={14} />,
            path: '',
          },
          {
            key: 'files',
            label: t('tenant.instances.tabs.files'),
            icon: <FileText size={14} />,
            path: '/files',
          },
          {
            key: 'channels',
            label: t('tenant.instances.tabs.channels'),
            icon: <Network size={14} />,
            path: '/channels',
          },
          {
            key: 'members',
            label: t('tenant.instances.tabs.members'),
            icon: <Users size={14} />,
            path: '/members',
          },
          {
            key: 'genes',
            label: t('tenant.instances.tabs.genes'),
            icon: <Dna size={14} />,
            path: '/genes',
          },
          {
            key: 'settings',
            label: t('tenant.instances.tabs.settings'),
            icon: <Settings size={14} />,
            path: '/settings',
          },
        ].map((tab) => (
          <button
            type="button"
            key={tab.key}
            onClick={() => {
              if (tab.path) {
                navigate(`.${tab.path}`);
              }
            }}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
              tab.key === 'overview'
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 hover:border-slate-300'
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
          <p className="text-sm text-slate-600 dark:text-slate-400">
            {t('tenant.instances.detail.status')}
          </p>
          <p className="text-lg font-semibold mt-1">
            {t(`tenant.instances.status.${instance.status}`)}
          </p>
        </Card>
        <Card className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
          <p className="text-sm text-slate-600 dark:text-slate-400">
            {t('tenant.instances.detail.replicas')}
          </p>
          <p className="text-lg font-semibold mt-1">
            {instance.available_replicas || 0} / {instance.replicas}
          </p>
        </Card>
        <Card className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
          <p className="text-sm text-slate-600 dark:text-slate-400">
            {t('tenant.instances.detail.imageVersion')}
          </p>
          <p className="text-lg font-semibold mt-1">{instance.image_version}</p>
        </Card>
        <Card className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
          <p className="text-sm text-slate-600 dark:text-slate-400">
            {t('tenant.instances.detail.runtime')}
          </p>
          <p className="text-lg font-semibold mt-1">{instance.runtime}</p>
        </Card>
      </div>

      {instance.proxy_token && (
        <Card
          title={t('tenant.instances.detail.proxyToken')}
          className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700"
        >
          <div className="flex gap-4 items-center">
            <code className="bg-slate-100 dark:bg-slate-900 px-4 py-2 rounded flex-1 break-all">
              {instance.proxy_token}
            </code>
            <Button onClick={handleCopyToken}>{t('common.copy')}</Button>
          </div>
        </Card>
      )}

      <Card
        title={t('tenant.instances.detail.resources')}
        className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700"
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          <div>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {t('tenant.instances.detail.cpu')}
            </p>
            <p className="font-medium mt-1">
              {instance.cpu_request} / {instance.cpu_limit}
            </p>
          </div>
          <div>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {t('tenant.instances.detail.memory')}
            </p>
            <p className="font-medium mt-1">
              {instance.mem_request} / {instance.mem_limit}
            </p>
          </div>
          <div>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {t('tenant.instances.detail.storage')}
            </p>
            <p className="font-medium mt-1">
              {instance.storage_class || '-'} ({instance.storage_size || '-'})
            </p>
          </div>
          <div>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {t('tenant.instances.detail.quota')}
            </p>
            <p className="font-medium mt-1">
              CPU: {instance.quota_cpu || '-'}, Mem: {instance.quota_memory || '-'}, Pods:{' '}
              {instance.quota_max_pods || '-'}
            </p>
          </div>
        </div>
      </Card>

      <Card
        title={t('tenant.instances.detail.members')}
        className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-0"
        bodyStyle={{ padding: 0 }}
      >
        <Table
          columns={memberColumns}
          dataSource={members}
          rowKey="id"
          pagination={false}
          className="w-full"
        />
      </Card>

      <Card
        title={t('tenant.instances.detail.config')}
        className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700"
      >
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          <div>
            <h3 className="text-md font-medium mb-4">{t('tenant.instances.detail.envVars')}</h3>
            <pre className="bg-slate-100 dark:bg-slate-900 p-4 rounded-lg overflow-x-auto text-sm">
              {JSON.stringify(config?.env_vars || instance.env_vars, null, 2)}
            </pre>
          </div>
          <div>
            <h3 className="text-md font-medium mb-4">
              {t('tenant.instances.detail.advancedConfig')}
            </h3>
            <pre className="bg-slate-100 dark:bg-slate-900 p-4 rounded-lg overflow-x-auto text-sm">
              {JSON.stringify(config?.advanced_config || instance.advanced_config, null, 2)}
            </pre>
          </div>
        </div>
      </Card>

      <Modal
        title={t('tenant.instances.actions.scale')}
        open={scaleModalVisible}
        onOk={handleScale}
        onCancel={() => {
          setScaleModalVisible(false);
        }}
      >
        <div className="flex items-center gap-4 py-4">
          <span>{t('tenant.instances.detail.replicas')}:</span>
          <InputNumber
            min={0}
            max={10}
            value={newReplicas}
            onChange={(val) => {
              setNewReplicas(val || 0);
            }}
          />
        </div>
      </Modal>
    </div>
  );
};
