import React, { useCallback, useEffect, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Table, Tag, Card } from 'antd';
import {
  Eye,
  EyeOff,
  RefreshCw,
  Activity,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  Minus,
} from 'lucide-react';

import { LazyAlert, LazyButton, useLazyMessage } from '@/components/ui/lazyAntd';

import {
  useCurrentInstance,
  useInstanceMembers,
  useInstanceConfig,
  useInstanceStore,
} from '../../stores/instance';

import { formatDate, getStatusColor } from './utils/instanceUtils';

import type { InstanceMemberResponse } from '../../services/instanceService';
import type { ColumnsType } from 'antd/es/table';

interface HealthConfig {
  icon: React.ReactNode;
  color: string;
  bgColor: string;
}

const UNKNOWN_HEALTH_CONFIG: HealthConfig = {
  icon: <Minus className="h-4 w-4" />,
  color: 'text-gray-500 dark:text-gray-400',
  bgColor: 'bg-gray-50 dark:bg-gray-800/30',
};

const HEALTH_CONFIG: Record<string, HealthConfig> = {
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
  unknown: UNKNOWN_HEALTH_CONFIG,
};

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

export const InstanceOverview: React.FC = () => {
  const { t } = useTranslation();
  const messageApi = useLazyMessage();

  const [showToken, setShowToken] = useState<boolean>(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [membersLoadError, setMembersLoadError] = useState<string | null>(null);
  const [isMembersLoading, setIsMembersLoading] = useState<boolean>(false);
  const refreshTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const instance = useCurrentInstance();
  const members = useInstanceMembers();
  const config = useInstanceConfig();
  const listMembers = useInstanceStore((s) => s.listMembers);
  const fetchInstance = useInstanceStore((s) => s.getInstance);
  const instanceId = instance?.id ?? null;

  const loadMembers = useCallback(async () => {
    if (!instanceId) return;
    setIsMembersLoading(true);
    try {
      await listMembers(instanceId);
      setMembersLoadError(null);
    } catch (error) {
      setMembersLoadError(getErrorMessage(error));
    } finally {
      setIsMembersLoading(false);
    }
  }, [instanceId, listMembers]);

  useEffect(() => {
    void loadMembers();
  }, [loadMembers]);

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
      .finally(() => {
        setActionLoading(null);
      });
  }, [fetchInstance, instanceId, messageApi, t]);

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
      render: (role: string) => (
        <Tag color={role === 'admin' ? 'blue' : 'default'}>
          {t(`tenant.instances.members.roles.${role}`, role)}
        </Tag>
      ),
    },
    {
      title: t('tenant.instances.columns.createdAt'),
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date: string) => formatDate(date),
    },
  ];

  const formatUptime = (createdAt: string): string => {
    const diff = Date.now() - new Date(createdAt).getTime();
    const days = Math.floor(diff / 86400000);
    const hours = Math.floor((diff % 86400000) / 3600000);
    const minutes = Math.floor((diff % 3600000) / 60000);
    if (days > 0) {
      return t('tenant.instances.detail.uptimeDh', {
        days,
        hours,
        defaultValue: '{{days}}d {{hours}}h',
      });
    }
    if (hours > 0) {
      return t('tenant.instances.detail.uptimeHm', {
        hours,
        minutes,
        defaultValue: '{{hours}}h {{minutes}}m',
      });
    }
    return t('tenant.instances.detail.uptimeM', { minutes, defaultValue: '{{minutes}}m' });
  };

  if (!instance) {
    return null;
  }

  const healthKey = instance.health_status || 'unknown';
  const healthCfg = HEALTH_CONFIG[healthKey] ?? UNKNOWN_HEALTH_CONFIG;
  const healthLabel = t(`tenant.instances.health.${healthKey}`, healthKey);

  return (
    <div className="flex flex-col gap-6">
      {/* Health banner + actions */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-3">
          <div
            className={`flex items-center gap-2 rounded-full px-4 py-2 ${healthCfg.bgColor} ${healthCfg.color}`}
          >
            {healthCfg.icon}
            <span className="text-sm font-semibold">{healthLabel}</span>
          </div>
          <Tag color={getStatusColor(instance.status)} className="text-xs">
            {t(`tenant.instances.status.${instance.status}`, instance.status)}
          </Tag>
          <div className="flex items-center gap-1 text-xs text-text-secondary dark:text-text-muted">
            <Clock className="h-3.5 w-3.5" />
            <span>
              {t('tenant.instances.detail.uptime', 'Uptime')}: {formatUptime(instance.created_at)}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <LazyButton
            icon={
              <RefreshCw
                size={14}
                className={
                  actionLoading === 'refresh' ? 'animate-spin motion-reduce:animate-none' : ''
                }
              />
            }
            onClick={handleRefresh}
            loading={actionLoading === 'refresh'}
            size="small"
          >
            {t('common.refresh', 'Refresh')}
          </LazyButton>
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
          <p className={`text-lg font-semibold mt-1 ${healthCfg.color}`}>{healthLabel}</p>
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
              aria-label={
                showToken
                  ? t('tenant.instances.detail.hideToken', 'Hide token')
                  : t('tenant.instances.detail.showToken', 'Show token')
              }
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
        {membersLoadError && (
          <div className="border-b border-border-light p-4 dark:border-border-dark">
            <LazyAlert
              type="error"
              showIcon
              message={t(
                'tenant.instances.detail.membersLoadFailed',
                'Failed to load instance members'
              )}
              description={membersLoadError}
              action={
                <button
                  type="button"
                  onClick={() => {
                    void loadMembers();
                  }}
                  disabled={isMembersLoading}
                  className="inline-flex items-center justify-center rounded-md border border-red-300 px-3 py-1 text-sm font-medium text-red-700 transition-colors hover:bg-red-50 disabled:opacity-50 dark:border-red-700 dark:text-red-300 dark:hover:bg-red-950/30"
                >
                  {t('common.retry')}
                </button>
              }
            />
          </div>
        )}
        <Table
          columns={memberColumns}
          dataSource={members}
          rowKey="id"
          loading={isMembersLoading}
          pagination={false}
          scroll={{ x: 'max-content' }}
          className="max-w-full"
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
