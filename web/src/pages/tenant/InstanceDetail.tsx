import React, { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useNavigate, useLocation } from 'react-router-dom';

import { Table, Tag, Space, Card, InputNumber } from 'antd';
import {
  ArrowLeft,
  FileText,
  Network,
  Users,
  Dna,
  Settings,
  LayoutDashboard,
  Eye,
  EyeOff,
} from 'lucide-react';

import {
  LazyModal,
  LazySpin,
  LazyButton,
  LazyPopconfirm,
  useLazyMessage,
} from '@/components/ui/lazyAntd';

import {
  useCurrentInstance,
  useInstanceMembers,
  useInstanceConfig,
  useInstanceLoading,
  useInstanceActions,
  useInstanceStore,
} from '../../stores/instance';

import { getStatusColor } from './utils/instanceUtils';

import type { InstanceMemberResponse } from '../../services/instanceService';
import type { ColumnsType } from 'antd/es/table';

export const InstanceDetail: React.FC = () => {
  const { instanceId: id } = useParams<{ instanceId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();
  const messageApi = useLazyMessage();

  const [scaleModalVisible, setScaleModalVisible] = useState(false);
  const [newReplicas, setNewReplicas] = useState<number>(1);
  const [showToken, setShowToken] = useState<boolean>(false);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  const instance = useCurrentInstance();
  const members = useInstanceMembers();
  const config = useInstanceConfig();
  const isLoading = useInstanceLoading();
  const { getInstance, restartInstance, deleteInstance, scaleInstance } = useInstanceActions();
  const listMembers = useInstanceStore((s) => s.listMembers);

  useEffect(() => {
    if (id) {
      void getInstance(id);
      void listMembers(id);
    }
  }, [id, getInstance, listMembers]);

  const handleBack = () => {
    void navigate('..');
  };

  const handleRestart = async () => {
    if (!id) return;
    setIsSubmitting(true);
    try {
      await restartInstance(id);
      messageApi?.success(t('tenant.instances.restartSuccess'));
    } catch {
      messageApi?.error(t('tenant.instances.restartError'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!id) return;
    setIsSubmitting(true);
    try {
      await deleteInstance(id);
      messageApi?.success(t('tenant.instances.deleteSuccess'));
      void navigate('..');
    } catch {
      messageApi?.error(t('tenant.instances.deleteError'));
      setIsSubmitting(false);
    }
  };

  const handleScale = async () => {
    if (!id) return;
    setIsSubmitting(true);
    try {
      await scaleInstance(id, newReplicas);
      messageApi?.success(t('tenant.instances.scaleSuccess'));
      setScaleModalVisible(false);
    } catch {
      messageApi?.error(t('tenant.instances.scaleError'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCopyToken = () => {
    if (instance?.proxy_token) {
      void navigator.clipboard.writeText(instance.proxy_token);
      messageApi?.success(t('tenant.instances.tokenCopied'));
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
        <LazyButton type="link" danger className="p-0">
          {t('tenant.instances.actions.removeMember')}
        </LazyButton>
      ),
    },
  ];

  if (!instance) {
    return (
      <div className="p-8 text-center flex justify-center">
        {isLoading ? <LazySpin size="large" /> : t('common.notFound')}
      </div>
    );
  }

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-8">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <LazyButton
            type="text"
            icon={<ArrowLeft size={16} />}
            onClick={handleBack}
            aria-label={t('common.back', 'Go back')}
          />
          <div>
            <h1 className="text-2xl font-bold text-text-primary dark:text-text-inverse flex items-center gap-3">
              {instance.name}
              <Tag color={getStatusColor(instance.status)} className="m-0">
                {t(`tenant.instances.status.${instance.status}`)}
              </Tag>
            </h1>
            <p className="text-sm text-text-muted mt-1">ID: {instance.id}</p>
          </div>
        </div>
        <Space>
          <LazyButton
            onClick={() => {
              setNewReplicas(instance.replicas);
              setScaleModalVisible(true);
            }}
            disabled={isSubmitting}
          >
            {t('tenant.instances.actions.scale')}
          </LazyButton>
          <LazyPopconfirm
            title={t('tenant.instances.actions.restartConfirm')}
            onConfirm={() => {
              void handleRestart();
            }}
            okText={t('common.yes')}
            cancelText={t('common.no')}
            okButtonProps={{ loading: isSubmitting }}
          >
            <LazyButton disabled={isSubmitting}>{t('tenant.instances.actions.restart')}</LazyButton>
          </LazyPopconfirm>
          <LazyPopconfirm
            title={t('tenant.instances.actions.deleteConfirm')}
            onConfirm={() => {
              void handleDelete();
            }}
            okText={t('common.yes')}
            cancelText={t('common.no')}
            okButtonProps={{ danger: true, loading: isSubmitting }}
          >
            <LazyButton danger disabled={isSubmitting}>
              {t('tenant.instances.actions.delete')}
            </LazyButton>
          </LazyPopconfirm>
        </Space>
      </div>

      <div className="flex items-center gap-1 border-b border-border-light dark:border-border-dark -mb-2">
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
          <LazyButton
            type="text"
            key={tab.key}
            onClick={() => {
              if (tab.path) {
                void navigate(`.${tab.path}`);
              }
            }}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px rounded-none h-auto ${
              (
                tab.key === 'overview'
                  ? location.pathname.split('/').pop() === id
                  : location.pathname.split('/').pop() === tab.key
              )
                ? 'border-info text-info-dark dark:text-info-light'
                : 'border-transparent text-text-muted hover:text-text-secondary dark:text-text-muted dark:hover:text-text-inverse hover:border-border-separator'
            }`}
          >
            {tab.icon}
            {tab.label}
          </LazyButton>
        ))}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card className="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark">
          <p className="text-sm text-text-secondary dark:text-text-muted">
            {t('tenant.instances.detail.status')}
          </p>
          <p className="text-lg font-semibold mt-1">
            {t(`tenant.instances.status.${instance.status}`)}
          </p>
        </Card>
        <Card className="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark">
          <p className="text-sm text-text-secondary dark:text-text-muted">
            {t('tenant.instances.detail.replicas')}
          </p>
          <p className="text-lg font-semibold mt-1">
            {instance.available_replicas || 0} / {instance.replicas}
          </p>
        </Card>
        <Card className="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark">
          <p className="text-sm text-text-secondary dark:text-text-muted">
            {t('tenant.instances.detail.imageVersion')}
          </p>
          <p className="text-lg font-semibold mt-1">{instance.image_version}</p>
        </Card>
        <Card className="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark">
          <p className="text-sm text-text-secondary dark:text-text-muted">
            {t('tenant.instances.detail.runtime')}
          </p>
          <p className="text-lg font-semibold mt-1">{instance.runtime}</p>
        </Card>
      </div>

      {instance.proxy_token && (
        <Card
          title={t('tenant.instances.detail.proxyToken')}
          className="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark"
        >
          <div className="flex gap-4 items-center">
            <code className="bg-surface-muted dark:bg-surface-dark-alt px-4 py-2 rounded flex-1 break-all">
              {showToken ? instance.proxy_token : '••••••••••••••••••••••••••••••••'}
            </code>
            <LazyButton
              icon={showToken ? <EyeOff size={16} /> : <Eye size={16} />}
              onClick={() => {
                setShowToken(!showToken);
              }}
              aria-label={showToken ? 'Hide token' : 'Show token'}
            />
            <LazyButton onClick={handleCopyToken}>{t('common.copy')}</LazyButton>
          </div>
        </Card>
      )}

      <Card
        title={t('tenant.instances.detail.resources')}
        className="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark"
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          <div>
            <p className="text-sm text-text-secondary dark:text-text-muted">
              {t('tenant.instances.detail.cpu')}
            </p>
            <p className="font-medium mt-1">
              {instance.cpu_request} / {instance.cpu_limit}
            </p>
          </div>
          <div>
            <p className="text-sm text-text-secondary dark:text-text-muted">
              {t('tenant.instances.detail.memory')}
            </p>
            <p className="font-medium mt-1">
              {instance.mem_request} / {instance.mem_limit}
            </p>
          </div>
          <div>
            <p className="text-sm text-text-secondary dark:text-text-muted">
              {t('tenant.instances.detail.storage')}
            </p>
            <p className="font-medium mt-1">
              {instance.storage_class || '-'} ({instance.storage_size || '-'})
            </p>
          </div>
          <div>
            <p className="text-sm text-text-secondary dark:text-text-muted">
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
        className="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark p-0"
        styles={{ body: { padding: 0 } }}
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
        className="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark"
      >
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          <div>
            <h3 className="text-md font-medium mb-4">{t('tenant.instances.detail.envVars')}</h3>
            <pre className="bg-surface-muted dark:bg-surface-dark-alt p-4 rounded-lg overflow-x-auto text-sm">
              {JSON.stringify(config?.env_vars || instance.env_vars, null, 2)}
            </pre>
          </div>
          <div>
            <h3 className="text-md font-medium mb-4">
              {t('tenant.instances.detail.advancedConfig')}
            </h3>
            <pre className="bg-surface-muted dark:bg-surface-dark-alt p-4 rounded-lg overflow-x-auto text-sm">
              {JSON.stringify(config?.advanced_config || instance.advanced_config, null, 2)}
            </pre>
          </div>
        </div>
      </Card>

      <LazyModal
        title={t('tenant.instances.actions.scale')}
        open={scaleModalVisible}
        onOk={() => {
          void handleScale();
        }}
        onCancel={() => {
          if (!isSubmitting) setScaleModalVisible(false);
        }}
        confirmLoading={isSubmitting}
        cancelButtonProps={{ disabled: isSubmitting }}
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
      </LazyModal>
    </div>
  );
};
