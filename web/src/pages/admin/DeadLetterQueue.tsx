/**
 * Dead Letter Queue Dashboard - DLQ 管理仪表板
 *
 * 显示 DLQ 状态、消息列表和统计数据。
 * 支持查看、重试和丢弃失败事件。
 *
 * @packageDocumentation
 */

import React, { useEffect, useState, useCallback } from 'react';

import {
  ReloadOutlined,
  RetweetOutlined,
  DeleteOutlined,
  ExclamationCircleOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  StopOutlined,
  WarningOutlined,
  EyeOutlined,
  ClearOutlined,
} from '@ant-design/icons';
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


import { dlqService } from '@/services/dlqService';
import type {
  DLQMessage,
  DLQMessageStatus,
  DLQStats,
} from '@/services/dlqService';

import type { ColumnsType } from 'antd/es/table';

const { Title, Text } = Typography;
const { TextArea } = Input;

// ============================================================================
// Helper Components
// ============================================================================

const StatusTag: React.FC<{ status: DLQMessageStatus }> = ({ status }) => {
  const config: Record<
    DLQMessageStatus,
    { color: string; icon: React.ReactNode; label: string }
  > = {
    pending: {
      color: 'warning',
      icon: <ClockCircleOutlined />,
      label: 'Pending',
    },
    retrying: {
      color: 'processing',
      icon: <RetweetOutlined />,
      label: 'Retrying',
    },
    discarded: {
      color: 'default',
      icon: <DeleteOutlined />,
      label: 'Discarded',
    },
    expired: {
      color: 'default',
      icon: <StopOutlined />,
      label: 'Expired',
    },
    resolved: {
      color: 'success',
      icon: <CheckCircleOutlined />,
      label: 'Resolved',
    },
  };

  const { color, icon, label } = config[status] || config.pending;

  return (
    <Tag color={color} icon={icon}>
      {label}
    </Tag>
  );
};

const formatAge = (seconds: number): string => {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
};

const formatDateTime = (iso: string): string => {
  return new Date(iso).toLocaleString();
};

// ============================================================================
// Main Component
// ============================================================================

const DeadLetterQueue: React.FC = () => {
  // State
  const [stats, setStats] = useState<DLQStats | null>(null);
  const [messages, setMessages] = useState<DLQMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [statsLoading, setStatsLoading] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [statusFilter, setStatusFilter] = useState<DLQMessageStatus | undefined>(
    undefined
  );
  const [eventTypeFilter, setEventTypeFilter] = useState<string | undefined>(
    undefined
  );
  const [errorTypeFilter, setErrorTypeFilter] = useState<string | undefined>(
    undefined
  );
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedMessage, setSelectedMessage] = useState<DLQMessage | null>(
    null
  );
  const [discardReason, setDiscardReason] = useState('');
  const [discardModalVisible, setDiscardModalVisible] = useState(false);
  const [messagesForDiscard, setMessagesForDiscard] = useState<string[]>([]);

  // Fetch stats
  const fetchStats = useCallback(async () => {
    setStatsLoading(true);
    try {
      const data = await dlqService.getStats();
      setStats(data);
    } catch (error) {
      message.error('Failed to load DLQ statistics');
    } finally {
      setStatsLoading(false);
    }
  }, []);

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
    } catch (error) {
      message.error('Failed to load DLQ messages');
    } finally {
      setLoading(false);
    }
  }, [statusFilter, eventTypeFilter, errorTypeFilter, pagination]);

  // Initial load
  useEffect(() => {
    fetchStats();
    fetchMessages();
  }, [fetchStats, fetchMessages]);

  // Refresh all
  const handleRefresh = () => {
    fetchStats();
    fetchMessages();
    setSelectedRowKeys([]);
  };

  // Retry single message
  const handleRetrySingle = async (messageId: string) => {
    try {
      await dlqService.retryMessage(messageId);
      message.success('Retry initiated');
      handleRefresh();
    } catch (error) {
      message.error('Failed to retry message');
    }
  };

  // Retry selected messages
  const handleRetryBatch = async () => {
    if (selectedRowKeys.length === 0) return;

    try {
      const result = await dlqService.retryMessages(
        selectedRowKeys as string[]
      );
      message.success(
        `Retry initiated: ${result.success_count} succeeded, ${result.failure_count} failed`
      );
      handleRefresh();
    } catch (error) {
      message.error('Failed to retry messages');
    }
  };

  // Open discard modal
  const openDiscardModal = (messageIds: string[]) => {
    setMessagesForDiscard(messageIds);
    setDiscardReason('');
    setDiscardModalVisible(true);
  };

  // Confirm discard
  const handleDiscardConfirm = async () => {
    if (!discardReason.trim()) {
      message.warning('Please provide a reason');
      return;
    }

    try {
      if (messagesForDiscard.length === 1) {
        await dlqService.discardMessage(messagesForDiscard[0], discardReason);
        message.success('Message discarded');
      } else {
        const result = await dlqService.discardMessages(
          messagesForDiscard,
          discardReason
        );
        message.success(
          `Discarded: ${result.success_count} succeeded, ${result.failure_count} failed`
        );
      }
      setDiscardModalVisible(false);
      handleRefresh();
    } catch (error) {
      message.error('Failed to discard message(s)');
    }
  };

  // Cleanup expired
  const handleCleanupExpired = async () => {
    try {
      const result = await dlqService.cleanupExpired();
      message.success(`Cleaned up ${result.cleaned_count} expired messages`);
      handleRefresh();
    } catch (error) {
      message.error('Failed to cleanup expired messages');
    }
  };

  // Cleanup resolved
  const handleCleanupResolved = async () => {
    try {
      const result = await dlqService.cleanupResolved();
      message.success(`Cleaned up ${result.cleaned_count} resolved messages`);
      handleRefresh();
    } catch (error) {
      message.error('Failed to cleanup resolved messages');
    }
  };

  // View message detail
  const viewMessageDetail = (msg: DLQMessage) => {
    setSelectedMessage(msg);
    setDetailModalVisible(true);
  };

  // Table columns
  const columns: ColumnsType<DLQMessage> = [
    {
      title: 'ID',
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
      title: 'Event Type',
      dataIndex: 'event_type',
      key: 'event_type',
      width: 140,
      render: (type: string) => <Tag color="blue">{type}</Tag>,
    },
    {
      title: 'Error Type',
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
      title: 'Error',
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
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: DLQMessageStatus) => <StatusTag status={status} />,
    },
    {
      title: 'Retries',
      key: 'retries',
      width: 80,
      render: (_, record) => (
        <Text type={record.retry_count >= record.max_retries ? 'danger' : undefined}>
          {record.retry_count}/{record.max_retries}
        </Text>
      ),
    },
    {
      title: 'Age',
      dataIndex: 'age_seconds',
      key: 'age',
      width: 80,
      render: (age: number) => formatAge(age),
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 120,
      render: (_, record) => (
        <Space size="small">
          <Tooltip title="View Details">
            <Button
              type="text"
              size="small"
              icon={<EyeOutlined />}
              onClick={() => viewMessageDetail(record)}
            />
          </Tooltip>
          {record.can_retry && (
            <Tooltip title="Retry">
              <Button
                type="text"
                size="small"
                icon={<RetweetOutlined />}
                onClick={() => handleRetrySingle(record.id)}
              />
            </Tooltip>
          )}
          {record.status === 'pending' && (
            <Tooltip title="Discard">
              <Button
                type="text"
                size="small"
                danger
                icon={<DeleteOutlined />}
                onClick={() => openDiscardModal([record.id])}
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
    onChange: (keys: React.Key[]) => setSelectedRowKeys(keys),
    getCheckboxProps: (record: DLQMessage) => ({
      disabled: record.status !== 'pending',
    }),
  };

  // Get unique values for filters
  const eventTypes = stats
    ? Object.keys(stats.event_type_counts)
    : [];
  const errorTypes = stats
    ? Object.keys(stats.error_type_counts)
    : [];

  return (
    <div style={{ padding: 24 }}>
      {/* Header */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 24 }}>
        <Col>
          <Title level={2} style={{ margin: 0 }}>
            <WarningOutlined style={{ marginRight: 8, color: '#faad14' }} />
            Dead Letter Queue
          </Title>
          <Text type="secondary">
            Failed events awaiting manual review or automatic retry
          </Text>
        </Col>
        <Col>
          <Space>
            <Popconfirm
              title="Clean up expired messages?"
              description="This will remove messages older than 1 week"
              onConfirm={handleCleanupExpired}
            >
              <Button icon={<ClearOutlined />}>Cleanup Expired</Button>
            </Popconfirm>
            <Popconfirm
              title="Clean up resolved messages?"
              description="This will remove successfully retried messages older than 24h"
              onConfirm={handleCleanupResolved}
            >
              <Button icon={<ClearOutlined />}>Cleanup Resolved</Button>
            </Popconfirm>
            <Button
              type="primary"
              icon={<ReloadOutlined />}
              onClick={handleRefresh}
              loading={loading || statsLoading}
            >
              Refresh
            </Button>
          </Space>
        </Col>
      </Row>

      {/* Statistics Cards */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={statsLoading}>
            <Statistic
              title="Total Messages"
              value={stats?.total_messages || 0}
              prefix={<ExclamationCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={statsLoading}>
            <Statistic
              title="Pending"
              value={stats?.pending_count || 0}
              valueStyle={{ color: '#faad14' }}
              prefix={<ClockCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={statsLoading}>
            <Statistic
              title="Retrying"
              value={stats?.retrying_count || 0}
              valueStyle={{ color: '#1890ff' }}
              prefix={<RetweetOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={statsLoading}>
            <Statistic
              title="Resolved"
              value={stats?.resolved_count || 0}
              valueStyle={{ color: '#52c41a' }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={statsLoading}>
            <Statistic
              title="Discarded"
              value={stats?.discarded_count || 0}
              valueStyle={{ color: '#8c8c8c' }}
              prefix={<DeleteOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={statsLoading}>
            <Statistic
              title="Oldest Age"
              value={stats ? formatAge(stats.oldest_message_age_seconds) : '-'}
              prefix={<ClockCircleOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* Error Type Distribution */}
      {stats && Object.keys(stats.error_type_counts).length > 0 && (
        <Card
          title="Error Type Distribution"
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
                      percent={Math.round(
                        (count / stats.pending_count) * 100
                      )}
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
            <Text strong>Filters:</Text>
          </Col>
          <Col>
            <Select
              placeholder="Status"
              allowClear
              style={{ width: 120 }}
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: 'pending', label: 'Pending' },
                { value: 'retrying', label: 'Retrying' },
                { value: 'discarded', label: 'Discarded' },
                { value: 'expired', label: 'Expired' },
                { value: 'resolved', label: 'Resolved' },
              ]}
            />
          </Col>
          <Col>
            <Select
              placeholder="Event Type"
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
              placeholder="Error Type"
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
                  <Text type="secondary">Selected</Text>
                </Badge>
              </Col>
              <Col>
                <Space>
                  <Button
                    type="primary"
                    icon={<RetweetOutlined />}
                    onClick={handleRetryBatch}
                  >
                    Retry Selected
                  </Button>
                  <Button
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() =>
                      openDiscardModal(selectedRowKeys as string[])
                    }
                  >
                    Discard Selected
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
            showTotal: (total) => `Total ${total} messages`,
            onChange: (page, pageSize) =>
              setPagination({ current: page, pageSize }),
          }}
          scroll={{ x: 900 }}
        />
      </Card>

      {/* Message Detail Modal */}
      <Modal
        title="Message Details"
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={[
          <Button key="close" onClick={() => setDetailModalVisible(false)}>
            Close
          </Button>,
          selectedMessage?.can_retry && (
            <Button
              key="retry"
              type="primary"
              icon={<RetweetOutlined />}
              onClick={() => {
                if (selectedMessage) {
                  handleRetrySingle(selectedMessage.id);
                  setDetailModalVisible(false);
                }
              }}
            >
              Retry
            </Button>
          ),
        ].filter(Boolean)}
        width={800}
      >
        {selectedMessage && (
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="Message ID" span={2}>
              <Text copyable>{selectedMessage.id}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="Event ID" span={2}>
              <Text copyable>{selectedMessage.event_id}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="Event Type">
              <Tag color="blue">{selectedMessage.event_type}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Status">
              <StatusTag status={selectedMessage.status} />
            </Descriptions.Item>
            <Descriptions.Item label="Routing Key" span={2}>
              <Text code>{selectedMessage.routing_key}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="Error Type" span={2}>
              <Tag color="red">{selectedMessage.error_type}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Error Message" span={2}>
              <Text type="danger">{selectedMessage.error}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="Retry Count">
              {selectedMessage.retry_count}/{selectedMessage.max_retries}
            </Descriptions.Item>
            <Descriptions.Item label="Age">
              {formatAge(selectedMessage.age_seconds)}
            </Descriptions.Item>
            <Descriptions.Item label="First Failed">
              {formatDateTime(selectedMessage.first_failed_at)}
            </Descriptions.Item>
            <Descriptions.Item label="Last Failed">
              {formatDateTime(selectedMessage.last_failed_at)}
            </Descriptions.Item>
            {selectedMessage.next_retry_at && (
              <Descriptions.Item label="Next Retry" span={2}>
                {formatDateTime(selectedMessage.next_retry_at)}
              </Descriptions.Item>
            )}
            <Descriptions.Item label="Event Data" span={2}>
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
                {JSON.stringify(
                  JSON.parse(selectedMessage.event_data),
                  null,
                  2
                )}
              </pre>
            </Descriptions.Item>
            {selectedMessage.error_traceback && (
              <Descriptions.Item label="Stack Trace" span={2}>
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
        title="Discard Message(s)"
        open={discardModalVisible}
        onCancel={() => setDiscardModalVisible(false)}
        onOk={handleDiscardConfirm}
        okText="Discard"
        okButtonProps={{ danger: true }}
      >
        <Alert
          type="warning"
          showIcon
          message={`You are about to discard ${messagesForDiscard.length} message(s). This action cannot be undone.`}
          style={{ marginBottom: 16 }}
        />
        <Text>Please provide a reason for discarding:</Text>
        <TextArea
          value={discardReason}
          onChange={(e) => setDiscardReason(e.target.value)}
          placeholder="e.g., Duplicate event, Stale data, Manual fix applied..."
          rows={3}
          style={{ marginTop: 8 }}
        />
      </Modal>
    </div>
  );
};

export default DeadLetterQueue;
