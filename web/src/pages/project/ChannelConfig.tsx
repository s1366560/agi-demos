import React, { useState, useEffect, useCallback, useRef } from 'react';

import { useParams } from 'react-router-dom';

import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ReloadOutlined,
  ExclamationCircleOutlined,
  MessageOutlined,
} from '@ant-design/icons';
import {
  Card,
  Button,
  Table,
  Tag,
  Space,
  Modal,
  Form,
  Input,
  Select,
  Switch,
  message,
  Popconfirm,
  Tooltip,
  Typography,
  Badge,
  InputNumber,
  Divider,
} from 'antd';
import { useShallow } from 'zustand/react/shallow';

import { useChannelStore } from '@/stores/channel';

import type { ChannelConfig, CreateChannelConfig, UpdateChannelConfig } from '@/types/channel';

const { Title, Text } = Typography;
const { Option } = Select;

const CHANNEL_TYPES = [
  { value: 'feishu', label: 'Feishu (Lark)', color: 'blue' },
  { value: 'dingtalk', label: 'DingTalk', color: 'orange', disabled: true },
  { value: 'wecom', label: 'WeCom', color: 'green', disabled: true },
  { value: 'slack', label: 'Slack', color: 'purple', disabled: true },
];

const CONNECTION_MODES = [
  { value: 'websocket', label: 'WebSocket (Recommended)' },
  { value: 'webhook', label: 'Webhook' },
];

const POLICY_OPTIONS = [
  { value: 'open', label: 'Open (all allowed)' },
  { value: 'allowlist', label: 'Allowlist (restricted)' },
  { value: 'disabled', label: 'Disabled' },
];

const STATUS_REFRESH_INTERVAL = 10_000;

const ChannelConfigPage: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [editingConfig, setEditingConfig] = useState<ChannelConfig | null>(null);
  const [form] = Form.useForm();
  const [testingConfig, setTestingConfig] = useState<string | null>(null);

  const {
    configs,
    loading,
    fetchConfigs,
    createConfig,
    updateConfig,
    deleteConfig,
    testConfig,
  } = useChannelStore(
    useShallow((state) => ({
      configs: state.configs,
      loading: state.loading,
      fetchConfigs: state.fetchConfigs,
      createConfig: state.createConfig,
      updateConfig: state.updateConfig,
      deleteConfig: state.deleteConfig,
      testConfig: state.testConfig,
    }))
  );

  useEffect(() => {
    if (projectId) {
      fetchConfigs(projectId);
    }
  }, [projectId, fetchConfigs]);

  // Auto-refresh status every 10s
  const intervalRef = useRef<ReturnType<typeof setInterval>>();
  useEffect(() => {
    if (projectId) {
      intervalRef.current = setInterval(() => {
        fetchConfigs(projectId);
      }, STATUS_REFRESH_INTERVAL);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [projectId, fetchConfigs]);

  const handleAdd = useCallback(() => {
    setEditingConfig(null);
    form.resetFields();
    setIsModalVisible(true);
  }, [form]);

  const handleEdit = useCallback((config: ChannelConfig) => {
    setEditingConfig(config);
    form.setFieldsValue({
      ...config,
      // Don't populate app_secret for security
      app_secret: undefined,
    });
    setIsModalVisible(true);
  }, [form]);

  const handleDelete = useCallback(async (id: string) => {
    try {
      await deleteConfig(id);
      message.success('Configuration deleted');
    } catch (error) {
      message.error('Failed to delete configuration');
    }
  }, [deleteConfig]);

  const handleTest = useCallback(async (id: string) => {
    setTestingConfig(id);
    try {
      const result = await testConfig(id);
      if (result.success) {
        message.success(result.message);
      } else {
        message.error(result.message);
      }
    } catch (error) {
      message.error('Test failed');
    } finally {
      setTestingConfig(null);
    }
  }, [testConfig]);

  const handleSubmit = useCallback(async (values: CreateChannelConfig | UpdateChannelConfig) => {
    try {
      if (editingConfig) {
        // Only include app_secret if it was changed
        const updateData: UpdateChannelConfig = { ...values };
        if (!updateData.app_secret) {
          delete updateData.app_secret;
        }
        await updateConfig(editingConfig.id, updateData);
        message.success('Configuration updated');
      } else {
        if (!projectId) {
          message.error('Project ID is required');
          return;
        }
        await createConfig(projectId, values as CreateChannelConfig);
        message.success('Configuration created');
      }
      setIsModalVisible(false);
      form.resetFields();
    } catch (error) {
      message.error('Failed to save configuration');
    }
  }, [editingConfig, projectId, createConfig, updateConfig, form]);

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'connected':
        return <Badge status="success" text="Connected" />;
      case 'error':
        return <Badge status="error" text="Error" />;
      case 'circuit_open':
        return <Badge color="orange" text="Circuit Open" />;
      default:
        return <Badge status="default" text="Disconnected" />;
    }
  };

  const columns = [
    {
      title: 'Name',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: ChannelConfig) => (
        <Space>
          <Text strong>{text}</Text>
          {record.enabled ? (
            <Tag color="success">Enabled</Tag>
          ) : (
            <Tag color="default">Disabled</Tag>
          )}
        </Space>
      ),
    },
    {
      title: 'Type',
      dataIndex: 'channel_type',
      key: 'channel_type',
      render: (type: string) => {
        const channelType = CHANNEL_TYPES.find((t) => t.value === type);
        return (
          <Tag color={channelType?.color || 'default'}>
            {channelType?.label || type}
          </Tag>
        );
      },
    },
    {
      title: 'Connection',
      dataIndex: 'connection_mode',
      key: 'connection_mode',
      render: (mode: string) => mode.toUpperCase(),
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      render: getStatusBadge,
    },
    {
      title: 'Last Error',
      dataIndex: 'last_error',
      key: 'last_error',
      ellipsis: true,
      render: (error: string | null) =>
        error ? (
          <Tooltip title={error}>
            <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />
            <Text type="danger" style={{ marginLeft: 8 }}>
              {error.slice(0, 30)}...
            </Text>
          </Tooltip>
        ) : null,
    },
    {
      title: 'Created',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date: string) => new Date(date).toLocaleDateString(),
    },
    {
      title: 'Actions',
      key: 'actions',
      render: (_: any, record: ChannelConfig) => (
        <Space>
          <Tooltip title="Test Connection">
            <Button
              icon={<ReloadOutlined />}
              size="small"
              loading={testingConfig === record.id}
              onClick={() => handleTest(record.id)}
            />
          </Tooltip>
          <Tooltip title="Edit">
            <Button
              icon={<EditOutlined />}
              size="small"
              onClick={() => handleEdit(record)}
            />
          </Tooltip>
          <Popconfirm
            title="Delete configuration?"
            description="This action cannot be undone."
            onConfirm={() => handleDelete(record.id)}
            okText="Delete"
            okButtonProps={{ danger: true }}
          >
            <Button icon={<DeleteOutlined />} size="small" danger />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={
          <Space>
            <MessageOutlined />
            <Title level={4} style={{ margin: 0 }}>
              Channel Integrations
            </Title>
          </Space>
        }
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
            Add Channel
          </Button>
        }
      >
        <Text type="secondary" style={{ marginBottom: 16, display: 'block' }}>
          Configure IM platform integrations (Feishu, DingTalk, WeCom) to enable
          AI agent communication through chat platforms.
        </Text>

        <Table
          dataSource={configs}
          columns={columns}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 10 }}
        />
      </Card>

      <Modal
        title={editingConfig ? 'Edit Channel Configuration' : 'Add Channel Configuration'}
        open={isModalVisible}
        onCancel={() => setIsModalVisible(false)}
        onOk={() => form.submit()}
        width={720}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
          initialValues={{
            channel_type: 'feishu',
            connection_mode: 'websocket',
            enabled: true,
            dm_policy: 'open',
            group_policy: 'open',
            rate_limit_per_minute: 60,
          }}
        >
          <Form.Item
            name="channel_type"
            label="Channel Type"
            rules={[{ required: true }]}
          >
            <Select placeholder="Select channel type">
              {CHANNEL_TYPES.map((type) => (
                <Option key={type.value} value={type.value} disabled={type.disabled}>
                  <Tag color={type.color}>{type.label}</Tag>
                  {type.disabled && <Text type="secondary"> (Coming soon)</Text>}
                </Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item
            name="name"
            label="Name"
            rules={[{ required: true, message: 'Please enter a name' }]}
          >
            <Input placeholder="e.g., Company Feishu Bot" />
          </Form.Item>

          <Form.Item name="enabled" label="Enabled" valuePropName="checked">
            <Switch />
          </Form.Item>

          <Form.Item
            name="connection_mode"
            label="Connection Mode"
            rules={[{ required: true }]}
          >
            <Select>
              {CONNECTION_MODES.map((mode) => (
                <Option key={mode.value} value={mode.value}>
                  {mode.label}
                </Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item
            name="app_id"
            label="App ID"
            rules={[{ required: true, message: 'Please enter App ID' }]}
          >
            <Input placeholder="cli_xxx" />
          </Form.Item>

          <Form.Item
            name="app_secret"
            label={`App Secret ${editingConfig ? '(leave blank to keep unchanged)' : ''}`}
            rules={editingConfig ? [] : [{ required: true, message: 'Please enter App Secret' }]}
          >
            <Input.Password placeholder="Enter app secret" />
          </Form.Item>

          <Form.Item name="encrypt_key" label="Encrypt Key (Optional)">
            <Input.Password placeholder="For webhook verification" />
          </Form.Item>

          <Form.Item name="verification_token" label="Verification Token (Optional)">
            <Input.Password placeholder="For webhook verification" />
          </Form.Item>

          <Form.Item name="webhook_url" label="Webhook URL (Optional)">
            <Input placeholder="https://your-domain.com/webhook" />
          </Form.Item>

          <Form.Item name="domain" label="Domain" initialValue="feishu">
            <Select>
              <Option value="feishu">Feishu (China)</Option>
              <Option value="lark">Lark (International)</Option>
            </Select>
          </Form.Item>

          <Form.Item name="description" label="Description (Optional)">
            <Input.TextArea rows={2} placeholder="Optional description" />
          </Form.Item>

          <Divider>Access Control</Divider>

          <Form.Item name="dm_policy" label="DM Policy">
            <Select>
              {POLICY_OPTIONS.map((opt) => (
                <Option key={opt.value} value={opt.value}>{opt.label}</Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item name="group_policy" label="Group Policy">
            <Select>
              {POLICY_OPTIONS.map((opt) => (
                <Option key={opt.value} value={opt.value}>{opt.label}</Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item
            name="allow_from"
            label="DM Allowlist (User IDs)"
            tooltip="User IDs allowed to DM the bot. Use * for all."
          >
            <Select mode="tags" placeholder="Enter user IDs (e.g., ou_xxx)" />
          </Form.Item>

          <Form.Item
            name="group_allow_from"
            label="Group Allowlist (Chat IDs)"
            tooltip="Group chat IDs where the bot can respond. Use * for all."
          >
            <Select mode="tags" placeholder="Enter group chat IDs (e.g., oc_xxx)" />
          </Form.Item>

          <Form.Item
            name="rate_limit_per_minute"
            label="Rate Limit (per minute per chat)"
            tooltip="0 = unlimited"
          >
            <InputNumber min={0} max={1000} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default ChannelConfigPage;
