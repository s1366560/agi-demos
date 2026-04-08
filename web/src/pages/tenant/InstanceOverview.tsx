import React, { useCallback, useEffect, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Table, Tag, Card, Popconfirm, InputNumber } from 'antd';
import {
  Eye,
  EyeOff,
  RefreshCw,
  Activity,
  ArrowUpDown,
  RotateCcw,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  Minus,
} from 'lucide-react';

import { LazyButton, useLazyMessage } from '@/components/ui/lazyAntd';

import {
  useCurrentInstance,
  useInstanceMembers,
  useInstanceConfig,
  useInstanceStore,
} from '../../stores/instance';

import type { InstanceMemberResponse } from '../../services/instanceService';
import type { ColumnsType } from 'antd/es/table';

const HEALTH_CONFIG: Record<string, { icon: React.ReactNode; color: string; bgColor: string }> = {
  healthy: {
    icon: <CheckCircle2 className="h-4 w-4" />,
    color: 'text-emerald-600 dark:text-emerald-400',
    bgColor: 'bg-emerald-50 dark:bg-emerald-900/20',
  },
  degraded: {
    icon: <AlertTriangle className="h-4 w-4" />,
    color: 'text-amber-600 dark:text-amber-400',
    bgColor: 'bg-amber-50 dark:bg-amber-900/20',
  },
  unhealthy: {
    icon: <XCircle className="h-4 w-4" />,
    color: 'text-red-600 dark:text-red-400',
    bgColor: 'bg-red-50 dark:bg-red-900/20',
  },
  unknown: {
    icon: <Minus className="h-4 w-4" />,
    color: 'text-gray-500 dark:text-gray-400',
    bgColor: 'bg-gray-50 dark:bg-gray-800/30',
  },
};

const STATUS_COLORS: Record<string, string> = {
  running: 'green',
  stopped: 'default',
  pending: 'orange',
  error: 'red',
  creating: 'blue',
  deleting: 'volcano',
};

function formatUptime(createdAt: string): string {
  const diff = Date.now() - new Date(createdAt).getTime();
  const days = Math.floor(diff / 86400000);
  const hours = Math.floor((diff % 86400000) / 3600000);
  if (days > 0) return `${days}d ${hours}h`;
  const minutes = Math.floor((diff % 3600000) / 60000);
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
}

export const InstanceOverview: React.FC = () => {
  const { t } = useTranslation();
  const messageApi = useLazyMessage();

  const [showToken, setShowToken] = useState<boolean>(false);
  const [scaleTarget, setScaleTarget] = useState<number | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const refreshTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const instance = useCurrentInstance();
  const members = useInstanceMembers();
  const config = useInstanceConfig();
  const listMembers = useInstanceStore((s) => s.listMembers);
  const scaleInstance = useInstanceStore((s) => s.scaleInstance);
  const restartInstance = useInstanceStore((s) => s.restartInstance);
  const fetchInstance = useInstanceStore((s) => s.getInstance);
  const instanceId = instance?.id ?? null;

  useEffect(() => {
    if (instanceId) {
      listMembers(instanceId);
    }
  }, [instanceId, listMembers]);

  // Auto-refresh instance status every 30s
  useEffect(() => {
    if (!instanceId) return;
    refreshTimerRef.current = setInterval(() => {
      fetchInstance(instanceId).catch(() => {});
    }, 30000);
    return () => {
      if (refreshTimerRef.current) clearInterval(refreshTimerRef.current);
    };
  }, [instanceId, fetchInstance]);

  const handleRefresh = useCallback(() => {
    if (!instanceId) return;
    setActionLoading('refresh');
    fetchInstance(instanceId)
      .then(() => messageApi?.success(t('common.refreshed', 'Refreshed')))
      .catch(() => messageApi?.error(t('common.error', 'Error')))
      .finally(() => setActionLoading(null));
  }, [fetchInstance, instanceId, messageApi, t]);

  const handleScale = useCallback(() => {
    if (!instanceId || scaleTarget === null) return;
    setActionLoading('scale');
    scaleInstance(instanceId, scaleTarget)
      .then(() => {
        messageApi?.success(t('tenant.instances.actions.scaleSuccess', 'Scaled successfully'));
        setScaleTarget(null);
      })
      .catch(() => messageApi?.error(t('tenant.instances.actions.scaleFailed', 'Scale failed')))
      .finally(() => setActionLoading(null));
  }, [instanceId, messageApi, scaleInstance, scaleTarget, t]);

  const handleRestart = useCallback(() => {
    if (!instanceId) return;
    setActionLoading('restart');
    restartInstance(instanceId)
      .then(() =>
        messageApi?.success(t('tenant.instances.actions.restartSuccess', 'Restart initiated')),
      )
      .catch(() =>
        messageApi?.error(t('tenant.instances.actions.restartFailed', 'Restart failed')),
      )
      .finally(() => setActionLoading(null));
  }, [instanceId, messageApi, restartInstance, t]);

  const handleCopyToken = () => {
    if (instance?.proxy_token) {
      navigator.clipboard.writeText(instance.proxy_token);
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
    return null;
  }

  const healthKey = instance.health_status || 'unknown';
  const healthCfg = HEALTH_CONFIG[healthKey] ?? HEALTH_CONFIG['unknown']!;

  return (
    <div className="flex flex-col gap-6">
      {/* Health banner + actions */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div
            className={`flex items-center gap-2 rounded-full px-4 py-2 ${healthCfg.bgColor} ${healthCfg.color}`}
          >
            {healthCfg.icon}
            <span className="text-sm font-semibold capitalize">{healthKey}</span>
          </div>
          <Tag color={STATUS_COLORS[instance.status] || 'default'} className="text-xs">
            {instance.status}
          </Tag>
          <div className="flex items-center gap-1 text-xs text-text-secondary dark:text-text-muted">
            <Clock className="h-3.5 w-3.5" />
            <span>
              {t('tenant.instances.detail.uptime', 'Uptime')}: {formatUptime(instance.created_at)}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <LazyButton
            icon={<RefreshCw size={14} className={actionLoading === 'refresh' ? 'animate-spin' : ''} />}
            onClick={handleRefresh}
            loading={actionLoading === 'refresh'}
            size="small"
          >
            {t('common.refresh', 'Refresh')}
          </LazyButton>
          <Popconfirm
            title={t('tenant.instances.actions.scaleTitle', 'Scale Instance')}
            description={
              <div className="flex items-center gap-2 py-2">
                <span>{t('tenant.instances.detail.replicas', 'Replicas')}:</span>
                <InputNumber
                  min={0}
                  max={10}
                  value={scaleTarget ?? instance.replicas}
                  onChange={(v) => setScaleTarget(v)}
                  size="small"
                />
              </div>
            }
            onConfirm={handleScale}
            okText={t('common.confirm', 'Confirm')}
            cancelText={t('common.cancel', 'Cancel')}
          >
            <LazyButton
              icon={<ArrowUpDown size={14} />}
              loading={actionLoading === 'scale'}
              size="small"
            >
              {t('tenant.instances.actions.scale', 'Scale')}
            </LazyButton>
          </Popconfirm>
          <Popconfirm
            title={t('tenant.instances.actions.restartConfirm', 'Restart this instance?')}
            onConfirm={handleRestart}
            okText={t('common.confirm', 'Confirm')}
            cancelText={t('common.cancel', 'Cancel')}
          >
            <LazyButton
              icon={<RotateCcw size={14} />}
              loading={actionLoading === 'restart'}
              size="small"
              danger
            >
              {t('tenant.instances.actions.restart', 'Restart')}
            </LazyButton>
          </Popconfirm>
        </div>
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card className="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark">
          <div className="flex items-center gap-2">
            <Activity className={`h-4 w-4 ${healthCfg.color}`} />
            <p className="text-sm text-text-secondary dark:text-text-muted">
              {t('tenant.instances.detail.health', 'Health')}
            </p>
          </div>
          <p className={`text-lg font-semibold mt-1 capitalize ${healthCfg.color}`}>{healthKey}</p>
        </Card>
        <Card className="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark">
          <p className="text-sm text-text-secondary dark:text-text-muted">
            {t('tenant.instances.detail.replicas')}
          </p>
          <p className="text-lg font-semibold mt-1">
            <span
              className={
                (instance.available_replicas || 0) < instance.replicas
                  ? 'text-amber-600 dark:text-amber-400'
                  : 'text-emerald-600 dark:text-emerald-400'
              }
            >
              {instance.available_replicas || 0}
            </span>{' '}
            / {instance.replicas}
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
    </div>
  );
};
