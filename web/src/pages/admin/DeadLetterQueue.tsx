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

import { formatDateTime } from '@/utils/date';

import type { ColumnsType } from 'antd/es/table';

const { Title, Text } = Typography;
const { TextArea } = Input;

// ============================================================================
// Helper Components
// ============================================================================

const StatusTag: React.FC<{ status: DLQMessageStatus }> = ({ status }) => {
  const config: Record<DLQMessageStatus, { color: string; icon: React.ReactNode; label: string }> =
    {
      pending: {
        color: 'warning',
        icon: <Clock size={16} />,
        label: 'Pending',
      },
      retrying: {
        color: 'processing',
        icon: <RefreshCcw size={16} />,
        label: 'Retrying',
      },
      discarded: {
        color: 'default',
        icon: <Trash2 size={16} />,
        label: 'Discarded',
      },
      expired: {
        color: 'default',
        icon: <Square size={16} />,
        label: 'Expired',
      },
      resolved: {
        color: 'success',
        icon: <CheckCircle2 size={16} />,
        label: 'Resolved',
      },
    };

  const { color, icon, label } = config[status];

  return (
    <Tag color={color} icon={icon}>
      {label}
    </Tag>
  );
};

const formatAge = (seconds: number): string => {
  if (seconds < 60) return `${String(Math.round(seconds))}s`;
  if (seconds < 3600) return `${String(Math.round(seconds / 60))}m`;
  if (seconds < 86400) return `${String(Math.round(seconds / 3600))}h`;
  return `${String(Math.round(seconds / 86400))}d`;
};

// ============================================================================
// Main Component
// ============================================================================

const DeadLetterQueue: React.FC = () => {
  const { t } = useTranslation();

  // State
  const [stats, setStats] = useState<DLQStats | null>(null);
  const [messages, setMessages] = useState<DLQMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [statsLoading, setStatsLoading] = useState(false);
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

  // Fetch stats
  const fetchStats = useCallback(async () => {
    setStatsLoading(true);
    try {
      const data = await dlqService.getStats();
      setStats(data);
    } catch (_error) {
      message.error(t('admin.deadLetterQueue.errors.failedToLoadStats'));
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
    } catch (_error) {
      message.error(t('admin.deadLetterQueue.errors.failedToLoadMessages'));
    } finally {
      setLoading(false);
    }
  }, [statusFilter, eventTypeFilter, errorTypeFilter, pagination, t]);

  // Initial load
  useEffect(() => {
    void fetchStats();
    void fetchMessages();
  }, [fetchStats, fetchMessages]);

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

    try {
      const result = await dlqService.retryMessages(selectedRowKeys as string[]);
      message.success(
        t('admin.deadLetterQueue.messages.retryBatchResult', {
          success: result.success_count,
          failure: result.failure_count,
        })
      );
      handleRefresh();
    } catch (_error) {
      message.error(t('admin.deadLetterQueue.errors.failedToRetryMessages'));
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

    try {
      if (messagesForDiscard.length === 1) {
        await dlqService.discardMessage(messagesForDiscard[0] ?? '', discardReason);
        message.success(t('admin.deadLetterQueue.messages.messageDiscarded'));
      } else {
        const result = await dlqService.discardMessages(messagesForDiscard, discardReason);
        message.success(
          t('admin.deadLetterQueue.messages.discardBatchResult', {
            success: result.success_count,
            failure: result.failure_count,
          })
        );
      }
      setDiscardModalVisible(false);
      handleRefresh();
    } catch (_error) {
      message.error(t('admin.deadLetterQueue.errors.failedToDiscardMessages'));
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
            {id.substring(0, 12)}...
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
      render: (status: DLQMessageStatus) => <StatusTag status={status} />,
    },
    {
      title: t('admin.deadLetterQueue.columns.retries'),
      key: 'retries',
      width: 80,
      render: (_, record) => (
        <Text type={record.retry_count >= record.max_retries ? 'danger' : 'secondary'}>
          {record.retry_count}/{record.max_retries}
        </Text>
      ),
    },
    {
      title: t('admin.deadLetterQueue.columns.age'),
      dataIndex: 'age_seconds',
      key: 'age',
      width: 80,
      render: (age: number) => formatAge(age),
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

  return (
    <div style={{ padding: 24 }}>
      {/* Header */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 24 }}>
        <Col>
          <Title level={2} style={{ margin: 0 }}>
            <AlertTriangle size={24} style={{ marginRight: 8, color: '#faad14' }} />
            {t('admin.deadLetterQueue.title')}
          </Title>
          <Text type="secondary">{t('admin.deadLetterQueue.description')}</Text>
        </Col>
        <Col>
          <Space>
            <Popconfirm
              title={t('admin.deadLetterQueue.confirm.cleanupExpired')}
              description={t('admin.deadLetterQueue.confirm.cleanupExpiredDesc')}
              onConfirm={() => void handleCleanupExpired()}
            >
              <Button icon={<Eraser size={16} />}>
                {t('admin.deadLetterQueue.actions.cleanupExpired')}
              </Button>
            </Popconfirm>
            <Popconfirm
              title={t('admin.deadLetterQueue.confirm.cleanupResolved')}
              description={t('admin.deadLetterQueue.confirm.cleanupResolvedDesc')}
              onConfirm={() => void handleCleanupResolved()}
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
              styles={{ content: { color: '#faad14' } }}
              prefix={<Clock size={20} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={statsLoading}>
            <Statistic
              title={t('admin.deadLetterQueue.stats.retrying')}
              value={stats?.retrying_count || 0}
              styles={{ content: { color: '#1890ff' } }}
              prefix={<RefreshCcw size={20} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={statsLoading}>
            <Statistic
              title={t('admin.deadLetterQueue.stats.resolved')}
              value={stats?.resolved_count || 0}
              styles={{ content: { color: '#52c41a' } }}
              prefix={<CheckCircle2 size={20} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={statsLoading}>
            <Statistic
              title={t('admin.deadLetterQueue.stats.discarded')}
              value={stats?.discarded_count || 0}
              styles={{ content: { color: '#8c8c8c' } }}
              prefix={<Trash2 size={20} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={statsLoading}>
            <Statistic
              title={t('admin.deadLetterQueue.stats.oldestAge')}
              value={stats ? formatAge(stats.oldest_message_age_seconds) : '-'}
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
                      percent={Math.round((count / stats.pending_count) * 100)}
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
              placeholder={t('admin.deadLetterQueue.filters.status')}
              allowClear
              style={{ width: 120 }}
              value={statusFilter}
              onChange={setStatusFilter}
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
              placeholder={t('admin.deadLetterQueue.filters.eventType')}
              allowClear
              style={{ width: 160 }}
              value={eventTypeFilter}
              onChange={setEventTypeFilter}
              options={eventTypes.map((t) => ({ value: t, label: t }))}
              showSearch
            />
          </Col>
          <Col>
            <Select
              placeholder={t('admin.deadLetterQueue.filters.errorType')}
              allowClear
              style={{ width: 200 }}
              value={errorTypeFilter}
              onChange={setErrorTypeFilter}
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
                    onClick={() => void handleRetryBatch()}
                  >
                    {t('admin.deadLetterQueue.actions.retrySelected')}
                  </Button>
                  <Button
                    danger
                    icon={<Trash2 size={16} />}
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
        <Table<DLQMessage>
          rowKey="id"
          columns={columns}
          dataSource={messages}
          loading={loading}
          rowSelection={rowSelection}
          pagination={{
            current: pagination.current,
            pageSize: pagination.pageSize,
            showSizeChanger: true,
            showTotal: (total) => `Total ${String(total)} messages`,
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
              <StatusTag status={selectedMessage.status} />
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
              {formatAge(selectedMessage.age_seconds)}
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
                  backgroundColor: '#f5f5f5',
                  padding: 8,
                  borderRadius: 4,
                  fontSize: 12,
                }}
              >
                {JSON.stringify(JSON.parse(selectedMessage.event_data), null, 2)}
              </pre>
            </Descriptions.Item>
            {selectedMessage.error_traceback && (
              <Descriptions.Item label={t('admin.deadLetterQueue.detail.stackTrace')} span={2}>
                <pre
                  style={{
                    maxHeight: 200,
                    overflow: 'auto',
                    backgroundColor: '#fff1f0',
                    padding: 8,
                    borderRadius: 4,
                    fontSize: 11,
                    color: '#cf1322',
                  }}
                >
                  {selectedMessage.error_traceback}
                </pre>
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
        okText={t('admin.deadLetterQueue.actions.discard')}
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
