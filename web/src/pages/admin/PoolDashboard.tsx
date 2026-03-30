/**
 * Agent Pool Dashboard - 池化管理仪表板
 *
 * 显示Agent Pool的状态、实例列表和指标数据。
 *
 * @packageDocumentation
 */

import React, { useEffect, useCallback, useRef } from 'react';

import { useTranslation } from 'react-i18next';

import {
  Card,
  Row,
  Col,
  Statistic,
  Table,
  Tag,
  Space,
  Button,
  Select,
  Tooltip,
  Progress,
  Switch,
  Typography,
  Alert,
  Popconfirm,
  message,
} from 'antd';
import {
  RefreshCw,
  PauseCircle,
  PlayCircle,
  Square,
  Zap,
  Cloud,
  History,
  CheckCircle2,
  AlertCircle,
  XCircle,
} from 'lucide-react';

import { formatDateTime } from '@/utils/date';

import { usePoolStore } from '../../stores/pool';

import type { PoolInstance, ProjectTier } from '../../services/poolService';
import type { ColumnsType } from 'antd/es/table';

const { Title, Text } = Typography;

// ============================================================================
// Helper Components
// ============================================================================

const TierTag: React.FC<{ tier: ProjectTier }> = ({ tier }) => {
  const config: Record<ProjectTier, { color: string; icon: React.ReactNode; label: string }> = {
    hot: { color: 'red', icon: <Zap size={16} />, label: 'HOT' },
    warm: { color: 'orange', icon: <Cloud size={16} />, label: 'WARM' },
    cold: { color: 'blue', icon: <History size={16} />, label: 'COLD' },
  };

  const { color, icon, label } = config[tier];

  return (
    <Tag color={color} icon={icon}>
      {label}
    </Tag>
  );
};

const StatusTag: React.FC<{ status: string }> = ({ status }) => {
  const config: Record<string, { color: string; icon: React.ReactNode }> = {
    ready: { color: 'green', icon: <CheckCircle2 size={16} /> },
    executing: { color: 'blue', icon: <Zap size={16} /> },
    paused: { color: 'orange', icon: <PauseCircle size={16} /> },
    unhealthy: { color: 'red', icon: <AlertCircle size={16} /> },
    degraded: { color: 'gold', icon: <AlertCircle size={16} /> },
    initializing: { color: 'cyan', icon: <RefreshCw size={16} className="animate-spin" /> },
    terminated: { color: 'default', icon: <Square size={16} /> },
    initialization_failed: { color: 'red', icon: <XCircle size={16} /> },
  };

  const { color, icon } = config[status] ?? { color: 'default', icon: null };

  return (
    <Tag color={color} icon={icon}>
      {status.toUpperCase()}
    </Tag>
  );
};

const HealthTag: React.FC<{ health: string }> = ({ health }) => {
  const config: Record<string, { color: string }> = {
    healthy: { color: 'green' },
    degraded: { color: 'gold' },
    unhealthy: { color: 'red' },
    unknown: { color: 'default' },
  };

  const { color } = config[health] ?? { color: 'default' };

  return <Tag color={color}>{health.toUpperCase()}</Tag>;
};

// ============================================================================
// Main Component
// ============================================================================

const PoolDashboard: React.FC = () => {
  const {
    // Status
    status,
    isStatusLoading,
    statusError,
    fetchStatus,
    // Instances
    instances,
    totalInstances,
    currentPage,
    pageSize,
    isInstancesLoading,
    instancesError,
    fetchInstances,
    setPage,
    setTierFilter,
    tierFilter,
    // Operations
    pauseInstance,
    resumeInstance,
    terminateInstance,
    // Metrics
    fetchMetrics,
    // Auto-refresh
    autoRefresh,
    setAutoRefresh,
    refreshInterval,
  } = usePoolStore();

  const refreshTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Initial load
  useEffect(() => {
    void fetchStatus();
    void fetchInstances();
    void fetchMetrics();
  }, [fetchStatus, fetchInstances, fetchMetrics]);

  // Auto-refresh
  useEffect(() => {
    if (autoRefresh) {
      refreshTimerRef.current = setInterval(() => {
        void fetchStatus();
        void fetchInstances();
        void fetchMetrics();
      }, refreshInterval * 1000);
    }

    return () => {
      if (refreshTimerRef.current) {
        clearInterval(refreshTimerRef.current);
      }
    };
  }, [autoRefresh, refreshInterval, fetchStatus, fetchInstances, fetchMetrics]);

  const { t } = useTranslation();

  const handleRefresh = useCallback(() => {
    void fetchStatus();
    void fetchInstances();
    void fetchMetrics();
  }, [fetchStatus, fetchInstances, fetchMetrics]);

  const handlePause = async (instanceKey: string) => {
    const success = await pauseInstance(instanceKey);
    if (success) {
      message.success(t('admin.poolDashboard.messages.instancePaused'));
    } else {
      message.error(t('admin.poolDashboard.messages.failedToPause'));
    }
  };

  const handleResume = async (instanceKey: string) => {
    const success = await resumeInstance(instanceKey);
    if (success) {
      message.success(t('admin.poolDashboard.messages.instanceResumed'));
    } else {
      message.error(t('admin.poolDashboard.messages.failedToResume'));
    }
  };

  const handleTerminate = async (instanceKey: string) => {
    const success = await terminateInstance(instanceKey);
    if (success) {
      message.success(t('admin.poolDashboard.messages.instanceTerminated'));
    } else {
      message.error(t('admin.poolDashboard.messages.failedToTerminate'));
    }
  };

  // Table columns
  const columns: ColumnsType<PoolInstance> = [
    {
      title: t('admin.poolDashboard.columns.instanceKey'),
      dataIndex: 'instance_key',
      key: 'instance_key',
      width: 250,
      ellipsis: true,
      render: (key: string) => (
        <Tooltip title={key}>
          <Text code style={{ fontSize: 12 }}>
            {key}
          </Text>
        </Tooltip>
      ),
    },
    {
      title: t('admin.poolDashboard.columns.tier'),
      dataIndex: 'tier',
      key: 'tier',
      width: 100,
      render: (tier: ProjectTier) => <TierTag tier={tier} />,
    },
    {
      title: t('admin.poolDashboard.columns.status'),
      dataIndex: 'status',
      key: 'status',
      width: 140,
      render: (status: string) => <StatusTag status={status} />,
    },
    {
      title: t('admin.poolDashboard.columns.health'),
      dataIndex: 'health_status',
      key: 'health_status',
      width: 100,
      render: (health: string) => <HealthTag health={health} />,
    },
    {
      title: t('admin.poolDashboard.columns.requests'),
      key: 'requests',
      width: 120,
      render: (_: unknown, record: PoolInstance) => (
        <Space orientation="vertical" size={0}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('admin.poolDashboard.columns.active')}: {record.active_requests}
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('admin.poolDashboard.columns.total')}: {record.total_requests}
          </Text>
        </Space>
      ),
    },
    {
      title: t('admin.poolDashboard.columns.memory'),
      dataIndex: 'memory_used_mb',
      key: 'memory_used_mb',
      width: 100,
      render: (mb: number) => `${mb.toFixed(1)} MB`,
    },
    {
      title: t('admin.poolDashboard.columns.lastRequest'),
      dataIndex: 'last_request_at',
      key: 'last_request_at',
      width: 160,
      render: (time: string | null) => (time ? formatDateTime(time) : '-'),
    },
    {
      title: t('admin.poolDashboard.columns.actions'),
      key: 'actions',
      width: 150,
      fixed: 'right',
      render: (_: unknown, record: PoolInstance) => (
        <Space size="small">
          {record.status === 'ready' || record.status === 'executing' ? (
            <Tooltip title={t('admin.poolDashboard.actions.pause')}>
              <Button
                type="text"
                size="small"
                icon={<PauseCircle size={16} />}
                onClick={() => void handlePause(record.instance_key)}
              />
            </Tooltip>
          ) : record.status === 'paused' ? (
            <Tooltip title={t('admin.poolDashboard.actions.resume')}>
              <Button
                type="text"
                size="small"
                icon={<PlayCircle size={16} />}
                onClick={() => void handleResume(record.instance_key)}
              />
            </Tooltip>
          ) : null}
          <Popconfirm
            title={t('admin.poolDashboard.confirm.terminateInstance')}
            onConfirm={() => void handleTerminate(record.instance_key)}
            okText={t('common.yes')}
            cancelText={t('common.no')}
          >
            <Tooltip title={t('admin.poolDashboard.actions.terminate')}>
              <Button type="text" size="small" danger icon={<Square size={16} />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // Calculate resource usage percentages
  const memoryUsagePct = status?.resource_usage
    ? (status.resource_usage.used_memory_mb / status.resource_usage.total_memory_mb) * 100
    : 0;
  const cpuUsagePct = status?.resource_usage
    ? (status.resource_usage.used_cpu_cores / status.resource_usage.total_cpu_cores) * 100
    : 0;

  // Format helpers for Progress components
  const formatMemoryProgress = (): string => {
    if (!status?.resource_usage) return '0 / 0 MB';
    const used = status.resource_usage.used_memory_mb.toFixed(0);
    const total = status.resource_usage.total_memory_mb.toFixed(0);
    return `${used} / ${total} MB`;
  };

  const formatCpuProgress = (): string => {
    if (!status?.resource_usage) return '0 / 0 cores';
    const used = status.resource_usage.used_cpu_cores.toFixed(1);
    const total = status.resource_usage.total_cpu_cores.toFixed(1);
    return `${used} / ${total} cores`;
  };

  return (
    <div style={{ padding: 24 }}>
      {/* Header */}
      <div
        style={{
          marginBottom: 24,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <Title level={2} style={{ margin: 0 }}>
          {t('admin.poolDashboard.title')}
        </Title>
        <Space>
          <Text type="secondary">{t('admin.poolDashboard.autoRefresh')}</Text>
          <Switch checked={autoRefresh} onChange={setAutoRefresh} size="small" />
          <Button
            icon={<RefreshCw size={16} />}
            onClick={handleRefresh}
            loading={isStatusLoading || isInstancesLoading}
          >
            {t('common.refresh')}
          </Button>
        </Space>
      </div>

      {/* Error alerts */}
      {statusError && (
        <Alert
          title={t('admin.poolDashboard.errors.failedToLoadPoolStatus')}
          description={statusError}
          type="error"
          showIcon
          closable
          style={{ marginBottom: 16 }}
        />
      )}

      {/* Status Overview */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={isStatusLoading}>
            <Statistic
              title={t('admin.poolDashboard.status.totalInstances')}
              value={status?.total_instances ?? 0}
              prefix={<Cloud size={20} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={isStatusLoading}>
            <Statistic
              title={t('admin.poolDashboard.status.ready')}
              value={status?.ready_instances ?? 0}
              styles={{ content: { color: '#52c41a' } }}
              prefix={<CheckCircle2 size={20} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={isStatusLoading}>
            <Statistic
              title={t('admin.poolDashboard.status.executing')}
              value={status?.executing_instances ?? 0}
              styles={{ content: { color: '#1890ff' } }}
              prefix={<Zap size={20} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={isStatusLoading}>
            <Statistic
              title={t('admin.poolDashboard.status.unhealthy')}
              value={status?.unhealthy_instances ?? 0}
              styles={{
                content: {
                  color: (status?.unhealthy_instances ?? 0) > 0 ? '#f5222d' : undefined,
                },
              }}
              prefix={<AlertCircle size={20} />}
            />
          </Card>
        </Col>
      </Row>

      {/* Tier Distribution & Resources */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} lg={12}>
          <Card title={t('admin.poolDashboard.tierDistribution')} loading={isStatusLoading}>
            <Row gutter={16}>
              <Col span={8}>
                <Statistic
                  title={
                    <Space>
                      <Zap size={16} style={{ color: '#f5222d' }} />
                      {t('admin.poolDashboard.tiers.hot')}
                    </Space>
                  }
                  value={status?.hot_instances ?? 0}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title={
                    <Space>
                      <Cloud size={16} style={{ color: '#fa8c16' }} />
                      {t('admin.poolDashboard.tiers.warm')}
                    </Space>
                  }
                  value={status?.warm_instances ?? 0}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title={
                    <Space>
                      <History size={16} style={{ color: '#1890ff' }} />
                      {t('admin.poolDashboard.tiers.cold')}
                    </Space>
                  }
                  value={status?.cold_instances ?? 0}
                />
              </Col>
            </Row>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title={t('admin.poolDashboard.resourceUsage')} loading={isStatusLoading}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <div>
                <Text type="secondary">{t('admin.poolDashboard.resources.memory')}</Text>
                <Progress
                  percent={Math.round(memoryUsagePct)}
                  status={memoryUsagePct > 80 ? 'exception' : 'normal'}
                  format={formatMemoryProgress}
                />
              </div>
              <div>
                <Text type="secondary">{t('admin.poolDashboard.resources.cpu')}</Text>
                <Progress
                  percent={Math.round(cpuUsagePct)}
                  status={cpuUsagePct > 80 ? 'exception' : 'normal'}
                  format={formatCpuProgress}
                />
              </div>
            </Space>
          </Card>
        </Col>
      </Row>

      {/* Prewarm Pool */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col span={24}>
          <Card title={t('admin.poolDashboard.prewarmPool')} loading={isStatusLoading}>
            <Row gutter={16}>
              <Col span={8}>
                <Statistic
                  title={t('admin.poolDashboard.prewarm.l1')}
                  value={status?.prewarm_pool.l1 ?? 0}
                  suffix={t('admin.poolDashboard.prewarm.instances')}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title={t('admin.poolDashboard.prewarm.l2')}
                  value={status?.prewarm_pool.l2 ?? 0}
                  suffix={t('admin.poolDashboard.prewarm.instances')}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title={t('admin.poolDashboard.prewarm.l3')}
                  value={status?.prewarm_pool.l3 ?? 0}
                  suffix={t('admin.poolDashboard.prewarm.instances')}
                />
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>

      {/* Instances Table */}
      <Card
        title={t('admin.poolDashboard.activeInstances')}
        extra={
          <Space>
            <Select
              placeholder={t('admin.poolDashboard.filterByTier')}
              allowClear
              style={{ width: 120 }}
              value={tierFilter}
              onChange={setTierFilter}
              options={[
                { value: 'hot', label: t('admin.poolDashboard.tiers.hot') },
                { value: 'warm', label: t('admin.poolDashboard.tiers.warm') },
                { value: 'cold', label: t('admin.poolDashboard.tiers.cold') },
              ]}
            />
          </Space>
        }
      >
        {instancesError && (
          <Alert title={instancesError} type="error" showIcon style={{ marginBottom: 16 }} />
        )}
        <Table
          columns={columns}
          dataSource={instances}
          rowKey="instance_key"
          loading={isInstancesLoading}
          pagination={{
            current: currentPage,
            pageSize: pageSize,
            total: totalInstances,
            showSizeChanger: true,
            showTotal: (total) => t('admin.poolDashboard.pagination.total', { count: total }),
            onChange: (page) => {
              setPage(page);
            },
          }}
          scroll={{ x: 1200 }}
          size="small"
        />
      </Card>
    </div>
  );
};

export default PoolDashboard;
