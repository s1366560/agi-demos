/**
 * Dead Letter Queue Dashboard - DLQ 管理仪表板
 *
 * 显示 DLQ 状态、消息列表和统计数据。
 * 支持查看、重试和丢弃失败事件。
 *
 * @packageDocumentation
 */

import React, { useEffect, useState, useCallback } from 'react';

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
  Typography,
  Alert,
  Popconfirm,
  message,
  Modal,
  Input,
  Descriptions,
  Badge,
  Progress,
  Switch,
  Empty,
} from 'antd';
import {
  RefreshCw,
  RefreshCcw,
  Trash2,
  AlertCircle,
  CheckCircle2,
  Clock,
  Square,
  AlertTriangle,
  Eye,
  Eraser,
} from 'lucide-react';

import { dlqService } from '@/services/dlqService';
import type { DLQMessage, DLQMessageStatus, DLQStats } from '@/services/dlqService';

import { useThemeColor } from '@/hooks/useThemeColor';

import { formatDateTime } from '@/utils/date';

import { StatusTag } from '@/components/common/StatusTag';

import type { ColumnsType } from 'antd/es/table';

const { Title, Text } = Typography;
const { TextArea } = Input;

// ============================================================================
// Helper Components
// ============================================================================

const DLQStatusTag: React.FC<{ status: DLQMessageStatus }> = ({ status }) => {
  const { t } = useTranslation();
  const config: Record<DLQMessageStatus, { color: string; icon: React.ReactNode; label: string }> =
    {
      pending: {
        color: 'warning',
        icon: <Clock size={16} />,
        label: t('admin.deadLetterQueue.statuses.pending'),
      },
      retrying: {
        color: 'processing',
        icon: <RefreshCcw size={16} />,
        label: t('admin.deadLetterQueue.statuses.retrying'),
      },
      discarded: {
        color: 'default',
        icon: <Trash2 size={16} />,
        label: t('admin.deadLetterQueue.statuses.discarded'),
      },
      expired: {
        color: 'default',
        icon: <Square size={16} />,
        label: t('admin.deadLetterQueue.statuses.expired'),
      },
      resolved: {
        color: 'success',
        icon: <CheckCircle2 size={16} />,
        label: t('admin.deadLetterQueue.statuses.resolved'),
      },
    };

  return <StatusTag {...config[status]} />;
};

const formatAge = (seconds: number, t: (key: string, defaultValue: string) => string): string => {
  if (seconds < 60)
    return `${String(Math.round(seconds))}${t('admin.deadLetterQueue.ageUnits.second', 's')}`;
  if (seconds < 3600)
    return `${String(Math.round(seconds / 60))}${t('admin.deadLetterQueue.ageUnits.minute', 'm')}`;
  if (seconds < 86400)
    return `${String(Math.round(seconds / 3600))}${t('admin.deadLetterQueue.ageUnits.hour', 'h')}`;
  return `${String(Math.round(seconds / 86400))}${t('admin.deadLetterQueue.ageUnits.day', 'd')}`;
};

/** Pretty-print the event payload; fall back to raw text when it is not valid JSON. */
const formatEventData = (raw: string): string => {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
};

const getDistributionPercent = (count: number, total: number): number => {
  if (total <= 0) return 0;
  return Math.round((count / total) * 100);
};

// ============================================================================
// Main Component
// ============================================================================

const DeadLetterQueue: React.FC = () => {
  const { t } = useTranslation();

  // Theme-aware status colors (resolved from design tokens)
  const warningColor = useThemeColor('--color-warning');
  const primaryColor = useThemeColor('--color-primary');
  const successColor = useThemeColor('--color-success');
  const mutedColor = useThemeColor('--color-muted');
  const errorColor = useThemeColor('--color-error');
  const codeBgColor = useThemeColor('--color-panel-2');

  // State
  const [stats, setStats] = useState<DLQStats | null>(null);
  const [messages, setMessages] = useState<DLQMessage[]>([]);
  const [totalMessages, setTotalMessages] = useState(0);
  const [loading, setLoading] = useState(false);
  const [statsLoading, setStatsLoading] = useState(false);
  const [messagesError, setMessagesError] = useState<string | null>(null);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [batchActionLoading, setBatchActionLoading] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [statusFilter, setStatusFilter] = useState<DLQMessageStatus | undefined>(undefined);
  const [eventTypeFilter, setEventTypeFilter] = useState<string | undefined>(undefined);
  const [errorTypeFilter, setErrorTypeFilter] = useState<string | undefined>(undefined);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedMessage, setSelectedMessage] = useState<DLQMessage | null>(null);
  const [discardReason, setDiscardReason] = useState('');
  const [discardModalVisible, setDiscardModalVisible] = useState(false);
  const [messagesForDiscard, setMessagesForDiscard] = useState<string[]>([]);

  // Changing a filter always restarts from the first page
  const handleStatusFilterChange = (value: DLQMessageStatus | undefined): void => {
    setStatusFilter(value);
    setPagination((prev) => ({ ...prev, current: 1 }));
  };
  const handleEventTypeFilterChange = (value: string | undefined): void => {
    setEventTypeFilter(value);
    setPagination((prev) => ({ ...prev, current: 1 }));
  };
  const handleErrorTypeFilterChange = (value: string | undefined): void => {
    setErrorTypeFilter(value);
    setPagination((prev) => ({ ...prev, current: 1 }));
  };

  // Fetch stats
  const fetchStats = useCallback(async () => {
    setStatsLoading(true);
    try {
      const data = await dlqService.getStats();
      setStats(data);
      setStatsError(null);
    } catch (error) {
      setStatsError(
        error instanceof Error ? error.message : t('admin.deadLetterQueue.errors.failedToLoadStats')
      );
    } finally {
      setStatsLoading(false);
    }
  }, [t]);

  // Fetch messages
  const fetchMessages = useCallback(async () => {
    setLoading(true);
    try {
      const data = await dlqService.listMessages({
        status: statusFilter,
        event_type: eventTypeFilter,
        error_type: errorTypeFilter,
        limit: pagination.pageSize,
        offset: (pagination.current - 1) * pagination.pageSize,
      });
      setMessages(data.messages);
      setTotalMessages(data.total);
      setMessagesError(null);
    } catch (error) {
      setMessagesError(
        error instanceof Error
          ? error.message
          : t('admin.deadLetterQueue.errors.failedToLoadMessages')
      );
    } finally {
      setLoading(false);
    }
  }, [statusFilter, eventTypeFilter, errorTypeFilter, pagination, t]);

  // Initial load
  useEffect(() => {
    void fetchStats();
    void fetchMessages();
  }, [fetchStats, fetchMessages]);

  // Auto-refresh (skipped while the tab is hidden), aligned with PoolDashboard
  useEffect(() => {
    if (!autoRefresh) return;
    const timer = setInterval(() => {
      if (document.visibilityState === 'hidden') return;
      void fetchStats();
      void fetchMessages();
    }, 30 * 1000);
    return () => {
      clearInterval(timer);
    };
  }, [autoRefresh, fetchStats, fetchMessages]);

  // Refresh all
  const handleRefresh = (): void => {
    void fetchStats();
    void fetchMessages();
    setSelectedRowKeys([]);
  };

  // Retry single message
  const handleRetrySingle = async (messageId: string): Promise<void> => {
    try {
      await dlqService.retryMessage(messageId);
      message.success(t('admin.deadLetterQueue.messages.retryInitiated'));
      handleRefresh();
    } catch (_error) {
      message.error(t('admin.deadLetterQueue.errors.failedToRetryMessage'));
    }
  };

  // Retry selected messages
  const handleRetryBatch = async (): Promise<void> => {
    if (selectedRowKeys.length === 0) return;

    setBatchActionLoading(true);
    try {
      const result = await dlqService.retryMessages(selectedRowKeys as string[]);
      message.success(
        t('admin.deadLetterQueue.messages.retryBatchResult', {
          count: result.success_count,
        })
      );
      handleRefresh();
    } catch (_error) {
      message.error(t('admin.deadLetterQueue.errors.failedToRetryMessages'));
    } finally {
      setBatchActionLoading(false);
    }
  };

  // Open discard modal
  const openDiscardModal = (messageIds: string[]): void => {
    setMessagesForDiscard(messageIds);
    setDiscardReason('');
    setDiscardModalVisible(true);
  };

  // Confirm discard
  const handleDiscardConfirm = async (): Promise<void> => {
    if (!discardReason.trim()) {
      message.warning(t('admin.deadLetterQueue.errors.reasonRequired'));
      return;
    }

    setBatchActionLoading(true);
    try {
      if (messagesForDiscard.length === 1) {
        await dlqService.discardMessage(messagesForDiscard[0] ?? '', discardReason);
        message.success(t('admin.deadLetterQueue.messages.messageDiscarded'));
      } else {
        const result = await dlqService.discardMessages(messagesForDiscard, discardReason);
        message.success(
          t('admin.deadLetterQueue.messages.discardBatchResult', {
            count: result.success_count,
          })
        );
      }
      setDiscardModalVisible(false);
      handleRefresh();
    } catch (_error) {
      message.error(t('admin.deadLetterQueue.errors.failedToDiscardMessages'));
    } finally {
      setBatchActionLoading(false);
    }
  };

  // Cleanup expired
  const handleCleanupExpired = async (): Promise<void> => {
    try {
      const result = await dlqService.cleanupExpired();
      message.success(
        t('admin.deadLetterQueue.messages.cleanupExpiredResult', {
          count: result.cleaned_count,
        })
      );
      handleRefresh();
    } catch (_error) {
      message.error(t('admin.deadLetterQueue.errors.failedToCleanupExpired'));
    }
  };

  // Cleanup resolved
  const handleCleanupResolved = async (): Promise<void> => {
    try {
      const result = await dlqService.cleanupResolved();
      message.success(
        t('admin.deadLetterQueue.messages.cleanupResolvedResult', {
          count: result.cleaned_count,
        })
      );
      handleRefresh();
    } catch (_error) {
      message.error(t('admin.deadLetterQueue.errors.failedToCleanupResolved'));
    }
  };

  // View message detail
  const viewMessageDetail = (msg: DLQMessage): void => {
    setSelectedMessage(msg);
    setDetailModalVisible(true);
  };

  // Table columns
  const columns: ColumnsType<DLQMessage> = [
    {
      title: t('admin.deadLetterQueue.columns.id'),
      dataIndex: 'id',
      key: 'id',
      width: 140,
      ellipsis: true,
      render: (id: string) => (
        <Tooltip title={id}>
          <Text copyable={{ text: id }} style={{ fontFamily: 'monospace' }}>
            {id.substring(0, 12)}…
          </Text>
        </Tooltip>
      ),
    },
    {
      title: t('admin.deadLetterQueue.columns.eventType'),
      dataIndex: 'event_type',
      key: 'event_type',
      width: 140,
      render: (type: string) => <Tag color="blue">{type}</Tag>,
    },
    {
      title: t('admin.deadLetterQueue.columns.errorType'),
      dataIndex: 'error_type',
      key: 'error_type',
      width: 140,
      ellipsis: true,
      render: (type: string) => (
        <Tooltip title={type}>
          <Tag color="red">{type.split('.').pop()}</Tag>
        </Tooltip>
      ),
    },
    {
      title: t('admin.deadLetterQueue.columns.error'),
      dataIndex: 'error',
      key: 'error',
      ellipsis: true,
      render: (error: string) => (
        <Tooltip title={error}>
          <Text type="secondary" ellipsis>
            {error}
          </Text>
        </Tooltip>
      ),
    },
    {
      title: t('admin.deadLetterQueue.columns.status'),
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: DLQMessageStatus) => <DLQStatusTag status={status} />,
    },
    {
      title: t('admin.deadLetterQueue.columns.retries'),
      key: 'retries',
      width: 80,
      render: (_, record) => (
        <Text
          type={record.retry_count >= record.max_retries ? 'danger' : 'secondary'}
          className="tabular-nums"
        >
          {record.retry_count}/{record.max_retries}
        </Text>
      ),
    },
    {
      title: t('admin.deadLetterQueue.columns.age'),
      dataIndex: 'age_seconds',
      key: 'age',
      width: 80,
      render: (age: number) => <span className="tabular-nums">{formatAge(age, t)}</span>,
    },
    {
      title: t('admin.deadLetterQueue.columns.actions'),
      key: 'actions',
      width: 120,
      render: (_, record) => (
        <Space size="small">
          <Tooltip title={t('admin.deadLetterQueue.actions.viewDetails')}>
            <Button
              type="text"
              size="small"
              icon={<Eye size={16} />}
              onClick={() => {
                viewMessageDetail(record);
              }}
            />
          </Tooltip>
          {record.can_retry && (
            <Tooltip title={t('admin.deadLetterQueue.actions.retry')}>
              <Button
                type="text"
                size="small"
                icon={<RefreshCcw size={16} />}
                onClick={() => void handleRetrySingle(record.id)}
              />
            </Tooltip>
          )}
          {record.status === 'pending' && (
            <Tooltip title={t('admin.deadLetterQueue.actions.discard')}>
              <Button
                type="text"
                size="small"
                danger
                icon={<Trash2 size={16} />}
                onClick={() => {
                  openDiscardModal([record.id]);
                }}
              />
            </Tooltip>
          )}
        </Space>
      ),
    },
  ];

  // Row selection
  const rowSelection = {
    selectedRowKeys,
    onChange: (keys: React.Key[]) => {
      setSelectedRowKeys(keys);
    },
    getCheckboxProps: (record: DLQMessage) => ({
      disabled: record.status !== 'pending',
    }),
  };

  // Get unique values for filters
  const eventTypes = stats ? Object.keys(stats.event_type_counts) : [];
  const errorTypes = stats ? Object.keys(stats.error_type_counts) : [];
  const errorTypeTotal = stats
    ? Object.values(stats.error_type_counts).reduce((total, count) => total + count, 0)
    : 0;

  return (
    <div style={{ padding: 24 }}>
      {/* Header */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 24 }}>
        <Col>
          <Title level={2} style={{ margin: 0 }}>
            <AlertTriangle size={24} style={{ marginRight: 8, color: warningColor }} />
            {t('admin.deadLetterQueue.title')}
          </Title>
          <Text type="secondary">{t('admin.deadLetterQueue.description')}</Text>
        </Col>
        <Col>
          <Space>
            <Text type="secondary">{t('admin.deadLetterQueue.autoRefresh', 'Auto Refresh')}</Text>
            <Switch
              checked={autoRefresh}
              onChange={setAutoRefresh}
              size="small"
              aria-label={t('admin.deadLetterQueue.autoRefresh', 'Auto Refresh')}
            />
            <Popconfirm
              title={t('admin.deadLetterQueue.confirm.cleanupExpired')}
              description={t('admin.deadLetterQueue.confirm.cleanupExpiredDesc')}
              onConfirm={() => void handleCleanupExpired()}
              okText={t('admin.deadLetterQueue.actions.cleanupExpired')}
              cancelText={t('common.cancel')}
            >
              <Button icon={<Eraser size={16} />}>
                {t('admin.deadLetterQueue.actions.cleanupExpired')}
              </Button>
            </Popconfirm>
            <Popconfirm
              title={t('admin.deadLetterQueue.confirm.cleanupResolved')}
              description={t('admin.deadLetterQueue.confirm.cleanupResolvedDesc')}
              onConfirm={() => void handleCleanupResolved()}
              okText={t('admin.deadLetterQueue.actions.cleanupResolved')}
              cancelText={t('common.cancel')}
            >
              <Button icon={<Eraser size={16} />}>
                {t('admin.deadLetterQueue.actions.cleanupResolved')}
              </Button>
            </Popconfirm>
            <Button
              type="primary"
              icon={<RefreshCw size={16} />}
              onClick={handleRefresh}
              loading={loading || statsLoading}
            >
              {t('common.refresh')}
            </Button>
          </Space>
        </Col>
      </Row>

      {/* Statistics load error (inline, with retry — never masquerade as an empty queue) */}
      {statsError && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          title={t('admin.deadLetterQueue.errors.failedToLoadStats')}
          description={statsError}
          action={
            <Button size="small" onClick={() => void fetchStats()}>
              {t('common.retry')}
            </Button>
          }
        />
      )}

      {/* Statistics Cards */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={statsLoading}>
            <Statistic
              title={t('admin.deadLetterQueue.stats.totalMessages')}
              value={stats?.total_messages || 0}
              prefix={<AlertCircle size={20} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={statsLoading}>
            <Statistic
              title={t('admin.deadLetterQueue.stats.pending')}
              value={stats?.pending_count || 0}
              styles={{ content: { color: warningColor } }}
              prefix={<Clock size={20} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={statsLoading}>
            <Statistic
              title={t('admin.deadLetterQueue.stats.retrying')}
              value={stats?.retrying_count || 0}
              styles={{ content: { color: primaryColor } }}
              prefix={<RefreshCcw size={20} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={statsLoading}>
            <Statistic
              title={t('admin.deadLetterQueue.stats.resolved')}
              value={stats?.resolved_count || 0}
              styles={{ content: { color: successColor } }}
              prefix={<CheckCircle2 size={20} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={statsLoading}>
            <Statistic
              title={t('admin.deadLetterQueue.stats.discarded')}
              value={stats?.discarded_count || 0}
              styles={{ content: { color: mutedColor } }}
              prefix={<Trash2 size={20} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={statsLoading}>
            <Statistic
              title={t('admin.deadLetterQueue.stats.oldestAge')}
              value={stats ? formatAge(stats.oldest_message_age_seconds, t) : '-'}
              prefix={<Clock size={20} />}
            />
          </Card>
        </Col>
      </Row>

      {/* Error Type Distribution */}
      {stats && Object.keys(stats.error_type_counts).length > 0 && (
        <Card
          title={t('admin.deadLetterQueue.errorTypeDistribution')}
          style={{ marginBottom: 24 }}
          loading={statsLoading}
        >
          <Row gutter={[16, 8]}>
            {Object.entries(stats.error_type_counts)
              .sort(([, a], [, b]) => b - a)
              .slice(0, 5)
              .map(([type, count]) => (
                <Col key={type} xs={24} sm={12} md={8} lg={6}>
                  <Space style={{ width: '100%' }}>
                    <Tag color="red">{type.split('.').pop()}</Tag>
                    <Progress
                      percent={getDistributionPercent(count, errorTypeTotal)}
                      size="small"
                      format={() => count}
                      style={{ flex: 1 }}
                    />
                  </Space>
                </Col>
              ))}
          </Row>
        </Card>
      )}

      {/* Filters and Batch Actions */}
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={[16, 16]} align="middle">
          <Col>
            <Text strong>{t('admin.deadLetterQueue.filters.label')}:</Text>
          </Col>
          <Col>
            <Select
              aria-label={t('admin.deadLetterQueue.filters.status')}
              placeholder={t('admin.deadLetterQueue.filters.status')}
              allowClear
              style={{ width: 120 }}
              value={statusFilter}
              onChange={handleStatusFilterChange}
              options={[
                { value: 'pending', label: t('admin.deadLetterQueue.statuses.pending') },
                { value: 'retrying', label: t('admin.deadLetterQueue.statuses.retrying') },
                { value: 'discarded', label: t('admin.deadLetterQueue.statuses.discarded') },
                { value: 'expired', label: t('admin.deadLetterQueue.statuses.expired') },
                { value: 'resolved', label: t('admin.deadLetterQueue.statuses.resolved') },
              ]}
            />
          </Col>
          <Col>
            <Select
              aria-label={t('admin.deadLetterQueue.filters.eventType')}
              placeholder={t('admin.deadLetterQueue.filters.eventType')}
              allowClear
              style={{ width: 160 }}
              value={eventTypeFilter}
              onChange={handleEventTypeFilterChange}
              options={eventTypes.map((t) => ({ value: t, label: t }))}
              showSearch
            />
          </Col>
          <Col>
            <Select
              aria-label={t('admin.deadLetterQueue.filters.errorType')}
              placeholder={t('admin.deadLetterQueue.filters.errorType')}
              allowClear
              style={{ width: 200 }}
              value={errorTypeFilter}
              onChange={handleErrorTypeFilterChange}
              options={errorTypes.map((t) => ({
                value: t,
                label: t.split('.').pop(),
              }))}
              showSearch
            />
          </Col>
          <Col flex="auto" />
          {selectedRowKeys.length > 0 && (
            <>
              <Col>
                <Badge count={selectedRowKeys.length}>
                  <Text type="secondary">{t('admin.deadLetterQueue.filters.selected')}</Text>
                </Badge>
              </Col>
              <Col>
                <Space>
                  <Button
                    type="primary"
                    icon={<RefreshCcw size={16} />}
                    loading={batchActionLoading}
                    onClick={() => void handleRetryBatch()}
                  >
                    {t('admin.deadLetterQueue.actions.retrySelected')}
                  </Button>
                  <Button
                    danger
                    icon={<Trash2 size={16} />}
                    disabled={batchActionLoading}
                    onClick={() => {
                      openDiscardModal(selectedRowKeys as string[]);
                    }}
                  >
                    {t('admin.deadLetterQueue.actions.discardSelected')}
                  </Button>
                </Space>
              </Col>
            </>
          )}
        </Row>
      </Card>

      {/* Messages Table */}
      <Card>
        {messagesError && (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            title={t('admin.deadLetterQueue.errors.failedToLoadMessages')}
            description={messagesError}
            action={
              <Button size="small" onClick={() => void fetchMessages()}>
                {t('common.retry')}
              </Button>
            }
          />
        )}
        <Table<DLQMessage>
          rowKey="id"
          columns={columns}
          dataSource={messages}
          loading={loading}
          rowSelection={rowSelection}
          locale={{
            emptyText: messagesError ? (
              ' '
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t(
                  'admin.deadLetterQueue.empty.description',
                  'No failed messages. The queue is healthy and nothing needs attention.'
                )}
              >
                <Button icon={<RefreshCw size={16} />} onClick={handleRefresh}>
                  {t('common.refresh')}
                </Button>
              </Empty>
            ),
          }}
          pagination={{
            current: pagination.current,
            pageSize: pagination.pageSize,
            total: totalMessages,
            showSizeChanger: true,
            showTotal: (total) => t('admin.deadLetterQueue.pagination.total', { count: total }),
            onChange: (page, pageSize) => {
              setPagination({ current: page, pageSize });
            },
          }}
          scroll={{ x: 900 }}
        />
      </Card>

      {/* Message Detail Modal */}
      <Modal
        title={t('admin.deadLetterQueue.detail.title')}
        open={detailModalVisible}
        onCancel={() => {
          setDetailModalVisible(false);
        }}
        footer={[
          <Button
            key="close"
            onClick={() => {
              setDetailModalVisible(false);
            }}
          >
            {t('common.close')}
          </Button>,
          selectedMessage?.can_retry && (
            <Button
              key="retry"
              type="primary"
              icon={<RefreshCcw size={16} />}
              onClick={() => {
                void handleRetrySingle(selectedMessage.id);
                setDetailModalVisible(false);
              }}
            >
              {t('admin.deadLetterQueue.actions.retry')}
            </Button>
          ),
        ].filter(Boolean)}
        width={800}
      >
        {selectedMessage && (
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label={t('admin.deadLetterQueue.columns.id')} span={2}>
              <Text copyable>{selectedMessage.id}</Text>
            </Descriptions.Item>
            <Descriptions.Item label={t('admin.deadLetterQueue.detail.eventId')} span={2}>
              <Text copyable>{selectedMessage.event_id}</Text>
            </Descriptions.Item>
            <Descriptions.Item label={t('admin.deadLetterQueue.columns.eventType')}>
              <Tag color="blue">{selectedMessage.event_type}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label={t('admin.deadLetterQueue.columns.status')}>
              <DLQStatusTag status={selectedMessage.status} />
            </Descriptions.Item>
            <Descriptions.Item label={t('admin.deadLetterQueue.detail.routingKey')} span={2}>
              <Text code>{selectedMessage.routing_key}</Text>
            </Descriptions.Item>
            <Descriptions.Item label={t('admin.deadLetterQueue.columns.errorType')} span={2}>
              <Tag color="red">{selectedMessage.error_type}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label={t('admin.deadLetterQueue.columns.error')} span={2}>
              <Text type="danger">{selectedMessage.error}</Text>
            </Descriptions.Item>
            <Descriptions.Item label={t('admin.deadLetterQueue.detail.retryCount')}>
              {selectedMessage.retry_count}/{selectedMessage.max_retries}
            </Descriptions.Item>
            <Descriptions.Item label={t('admin.deadLetterQueue.columns.age')}>
              {formatAge(selectedMessage.age_seconds, t)}
            </Descriptions.Item>
            <Descriptions.Item label={t('admin.deadLetterQueue.detail.firstFailed')}>
              {formatDateTime(selectedMessage.first_failed_at)}
            </Descriptions.Item>
            <Descriptions.Item label={t('admin.deadLetterQueue.detail.lastFailed')}>
              {formatDateTime(selectedMessage.last_failed_at)}
            </Descriptions.Item>
            {selectedMessage.next_retry_at && (
              <Descriptions.Item label={t('admin.deadLetterQueue.detail.nextRetry')} span={2}>
                {formatDateTime(selectedMessage.next_retry_at)}
              </Descriptions.Item>
            )}
            <Descriptions.Item label={t('admin.deadLetterQueue.detail.eventData')} span={2}>
              <pre
                style={{
                  maxHeight: 200,
                  overflow: 'auto',
                  backgroundColor: codeBgColor,
                  padding: 8,
                  borderRadius: 4,
                  fontSize: 12,
                }}
              >
                {formatEventData(selectedMessage.event_data)}
              </pre>
            </Descriptions.Item>
            {selectedMessage.error_traceback && (
              <Descriptions.Item label={t('admin.deadLetterQueue.detail.stackTrace')} span={2}>
                <details>
                  <summary style={{ cursor: 'pointer', marginBottom: 8 }}>
                    {t('admin.deadLetterQueue.detail.showStackTrace', 'Show stack trace')}
                  </summary>
                  <pre
                    style={{
                      maxHeight: 200,
                      overflow: 'auto',
                      backgroundColor: codeBgColor,
                      padding: 8,
                      borderRadius: 4,
                      fontSize: 11,
                      color: errorColor,
                    }}
                  >
                    {selectedMessage.error_traceback}
                  </pre>
                </details>
              </Descriptions.Item>
            )}
          </Descriptions>
        )}
      </Modal>

      {/* Discard Confirmation Modal */}
      <Modal
        title={t('admin.deadLetterQueue.discard.title')}
        open={discardModalVisible}
        onCancel={() => {
          setDiscardModalVisible(false);
        }}
        onOk={() => void handleDiscardConfirm()}
        confirmLoading={batchActionLoading}
        okText={t('admin.deadLetterQueue.actions.discardWithCount', {
          count: messagesForDiscard.length,
          defaultValue: 'Discard {{count}} message(s)',
        })}
        cancelText={t('common.cancel')}
        okButtonProps={{ danger: true }}
      >
        <Alert
          type="warning"
          showIcon
          title={t('admin.deadLetterQueue.discard.confirmMessage', {
            count: messagesForDiscard.length,
          })}
          style={{ marginBottom: 16 }}
        />
        <Text>{t('admin.deadLetterQueue.discard.reasonLabel')}</Text>
        <TextArea
          value={discardReason}
          onChange={(e) => {
            setDiscardReason(e.target.value);
          }}
          placeholder={t('admin.deadLetterQueue.discard.reasonPlaceholder')}
          rows={3}
          style={{ marginTop: 8 }}
        />
      </Modal>
    </div>
  );
};

export default DeadLetterQueue;
