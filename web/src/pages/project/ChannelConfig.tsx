import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';

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

import { channelService } from '@/services/channelService';

import type {
  ChannelConfig,
  CreateChannelConfig,
  UpdateChannelConfig,
  ChannelPluginConfigSchema,
  PluginActionDetails,
  RuntimePlugin,
  PluginDiagnostic,
  ChannelPluginCatalogItem,
} from '@/types/channel';

const { Title, Text } = Typography;
const { Option } = Select;

const CHANNEL_TYPE_META: Record<string, { label: string; color: string }> = {
  feishu: { label: 'Feishu (Lark)', color: 'blue' },
  dingtalk: { label: 'DingTalk', color: 'orange' },
  wecom: { label: 'WeCom', color: 'green' },
  slack: { label: 'Slack', color: 'purple' },
  telegram: { label: 'Telegram', color: 'cyan' },
};

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
const SECRET_UNCHANGED_SENTINEL = '__MEMSTACK_SECRET_UNCHANGED__';
const CHANNEL_SETTING_FIELDS = new Set([
  'app_id',
  'app_secret',
  'encrypt_key',
  'verification_token',
  'connection_mode',
  'webhook_url',
  'webhook_port',
  'webhook_path',
  'domain',
]);

const humanizeChannelType = (channelType: string): string =>
  channelType
    .split(/[-_]/g)
    .filter(Boolean)
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(' ');

const humanizeFieldName = (fieldName: string): string =>
  fieldName
    .split(/[-_]/g)
    .filter(Boolean)
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(' ');

const ChannelConfigPage: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [editingConfig, setEditingConfig] = useState<ChannelConfig | null>(null);
  const [form] = Form.useForm();
  const [testingConfig, setTestingConfig] = useState<string | null>(null);
  const [plugins, setPlugins] = useState<RuntimePlugin[]>([]);
  const [pluginDiagnostics, setPluginDiagnostics] = useState<PluginDiagnostic[]>([]);
  const [channelPluginCatalog, setChannelPluginCatalog] = useState<ChannelPluginCatalogItem[]>([]);
  const [channelSchemas, setChannelSchemas] = useState<Record<string, ChannelPluginConfigSchema>>(
    {}
  );
  const [pluginsLoading, setPluginsLoading] = useState(false);
  const [schemaLoading, setSchemaLoading] = useState(false);
  const [pluginActionKey, setPluginActionKey] = useState<string | null>(null);
  const [installRequirement, setInstallRequirement] = useState('');
  const [lastPluginActionDetails, setLastPluginActionDetails] =
    useState<PluginActionDetails | null>(null);

  const { configs, loading, fetchConfigs, createConfig, updateConfig, deleteConfig, testConfig } =
    useChannelStore(
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
  const selectedChannelType = Form.useWatch('channel_type', form);
  const activeChannelSchema = selectedChannelType ? channelSchemas[selectedChannelType] : undefined;

  const loadPluginRuntime = useCallback(async () => {
    if (!projectId) return;
    setPluginsLoading(true);
    try {
      const [pluginRes, catalogRes] = await Promise.all([
        channelService.listPlugins(projectId),
        channelService.listChannelPluginCatalog(projectId),
      ]);
      setPlugins(pluginRes.items);
      setPluginDiagnostics(pluginRes.diagnostics);
      setChannelPluginCatalog(catalogRes.items);
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Failed to load plugin runtime');
    } finally {
      setPluginsLoading(false);
    }
  }, [projectId]);

  const loadChannelSchema = useCallback(
    async (channelType: string) => {
      if (!projectId || !channelType) return;
      if (channelSchemas[channelType]) return;

      const catalogEntry = channelPluginCatalog.find((item) => item.channel_type === channelType);
      if (!catalogEntry?.schema_supported) return;

      setSchemaLoading(true);
      try {
        const schema = await channelService.getChannelPluginSchema(projectId, channelType);
        setChannelSchemas((prev) => ({ ...prev, [channelType]: schema }));
      } catch (error) {
        message.error(error instanceof Error ? error.message : 'Failed to load channel schema');
      } finally {
        setSchemaLoading(false);
      }
    },
    [channelPluginCatalog, channelSchemas, projectId]
  );

  const channelTypeOptions = useMemo(() => {
    if (channelPluginCatalog.length === 0) {
      return Object.entries(CHANNEL_TYPE_META).map(([value, meta]) => ({
        value,
        label: meta.label,
        color: meta.color,
      }));
    }
    return channelPluginCatalog.map((entry) => {
      const known = CHANNEL_TYPE_META[entry.channel_type];
      return {
        value: entry.channel_type,
        label: known?.label || humanizeChannelType(entry.channel_type),
        color: known?.color || 'geekblue',
      };
    });
  }, [channelPluginCatalog]);

  useEffect(() => {
    if (projectId) {
      fetchConfigs(projectId);
    }
  }, [projectId, fetchConfigs]);

  useEffect(() => {
    loadPluginRuntime();
  }, [loadPluginRuntime]);

  useEffect(() => {
    if (!selectedChannelType || !isModalVisible) return;
    void loadChannelSchema(selectedChannelType);
  }, [isModalVisible, loadChannelSchema, selectedChannelType]);

  useEffect(() => {
    if (!isModalVisible || editingConfig || !activeChannelSchema?.defaults) return;
    const defaults = activeChannelSchema.defaults;
    if (!defaults || typeof defaults !== 'object') return;

    const initialValues: Record<string, unknown> = {};
    const initialExtraSettings: Record<string, unknown> = {};
    Object.entries(defaults).forEach(([key, value]) => {
      if (CHANNEL_SETTING_FIELDS.has(key)) {
        initialValues[key] = value;
      } else {
        initialExtraSettings[key] = value;
      }
    });
    if (Object.keys(initialExtraSettings).length > 0) {
      initialValues.extra_settings = {
        ...(form.getFieldValue('extra_settings') || {}),
        ...initialExtraSettings,
      };
    }
    form.setFieldsValue(initialValues);
  }, [activeChannelSchema, editingConfig, form, isModalVisible]);

  // Auto-refresh status every 10s
  const intervalRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
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

  const handleEdit = useCallback(
    (config: ChannelConfig) => {
      setEditingConfig(config);
      void loadChannelSchema(config.channel_type);
      form.setFieldsValue({
        ...config,
        // Don't populate app_secret for security
        app_secret: undefined,
      });
      setIsModalVisible(true);
    },
    [form, loadChannelSchema]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteConfig(id);
        message.success('Configuration deleted');
      } catch (_error) {
        message.error('Failed to delete configuration');
      }
    },
    [deleteConfig]
  );

  const handleTest = useCallback(
    async (id: string) => {
      setTestingConfig(id);
      try {
        const result = await testConfig(id);
        if (result.success) {
          message.success(result.message);
        } else {
          message.error(result.message);
        }
      } catch (_error) {
        message.error('Test failed');
      } finally {
        setTestingConfig(null);
      }
    },
    [testConfig]
  );

  const handleInstallPlugin = useCallback(async () => {
    if (!projectId) return;
    if (!installRequirement.trim()) {
      message.warning('Please enter a plugin requirement');
      return;
    }
    setPluginActionKey('install');
    try {
      const response = await channelService.installPlugin(projectId, installRequirement.trim());
      setLastPluginActionDetails(response.details || null);
      message.success(response.message);
      setInstallRequirement('');
      await loadPluginRuntime();
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Plugin install failed');
    } finally {
      setPluginActionKey(null);
    }
  }, [installRequirement, loadPluginRuntime, projectId]);

  const handleTogglePlugin = useCallback(
    async (plugin: RuntimePlugin, enabled: boolean) => {
      if (!projectId) return;
      setPluginActionKey(`${plugin.name}:${enabled ? 'enable' : 'disable'}`);
      try {
        const response = enabled
          ? await channelService.enablePlugin(projectId, plugin.name)
          : await channelService.disablePlugin(projectId, plugin.name);
        setLastPluginActionDetails(response.details || null);
        if (enabled) {
          message.success(`Plugin enabled: ${plugin.name}`);
        } else {
          message.success(`Plugin disabled: ${plugin.name}`);
        }
        await loadPluginRuntime();
      } catch (error) {
        message.error(error instanceof Error ? error.message : 'Plugin action failed');
      } finally {
        setPluginActionKey(null);
      }
    },
    [loadPluginRuntime, projectId]
  );

  const handleReloadPlugins = useCallback(async () => {
    if (!projectId) return;
    setPluginActionKey('reload');
    try {
      const response = await channelService.reloadPlugins(projectId);
      setLastPluginActionDetails(response.details || null);
      message.success(response.message);
      await loadPluginRuntime();
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Plugin reload failed');
    } finally {
      setPluginActionKey(null);
    }
  }, [loadPluginRuntime, projectId]);

  const handleSubmit = useCallback(
    async (values: CreateChannelConfig | UpdateChannelConfig) => {
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
      } catch (_error) {
        message.error('Failed to save configuration');
      }
    },
    [editingConfig, projectId, createConfig, updateConfig, form]
  );

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
        const channelType = channelTypeOptions.find((option) => option.value === type);
        return (
          <Tag color={channelType?.color || 'default'}>
            {channelType?.label || humanizeChannelType(type)}
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
            <Button icon={<EditOutlined />} size="small" onClick={() => { handleEdit(record); }} />
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

  const pluginColumns = [
    {
      title: 'Plugin',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: RuntimePlugin) => (
        <Space direction="vertical" size={0}>
          <Text strong>{name}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {record.package || 'local'}
            {record.version ? `@${record.version}` : ''}
          </Text>
        </Space>
      ),
    },
    {
      title: 'Source',
      dataIndex: 'source',
      key: 'source',
      render: (source: string) => <Tag>{source}</Tag>,
    },
    {
      title: 'Channels',
      dataIndex: 'channel_types',
      key: 'channel_types',
      render: (channelTypes: string[]) =>
        channelTypes.length > 0 ? (
          <Space wrap>
            {channelTypes.map((channelType) => (
              <Tag key={channelType} color="blue">
                {humanizeChannelType(channelType)}
              </Tag>
            ))}
          </Space>
        ) : (
          <Text type="secondary">Tool-only plugin</Text>
        ),
    },
    {
      title: 'Status',
      key: 'status',
      render: (_: unknown, record: RuntimePlugin) =>
        record.enabled ? (
          <Badge status="success" text="Enabled" />
        ) : (
          <Badge status="default" text="Disabled" />
        ),
    },
    {
      title: 'Actions',
      key: 'actions',
      render: (_: unknown, record: RuntimePlugin) => (
        <Space>
          {record.enabled ? (
            <Button
              size="small"
              loading={pluginActionKey === `${record.name}:disable`}
              onClick={() => handleTogglePlugin(record, false)}
            >
              Disable
            </Button>
          ) : (
            <Button
              size="small"
              type="primary"
              ghost
              loading={pluginActionKey === `${record.name}:enable`}
              onClick={() => handleTogglePlugin(record, true)}
            >
              Enable
            </Button>
          )}
        </Space>
      ),
    },
  ];

  const dynamicSchemaFields = useMemo(() => {
    if (!activeChannelSchema?.schema_supported) return [];
    const properties = activeChannelSchema.config_schema?.properties || {};
    const requiredFields = new Set(activeChannelSchema.config_schema?.required || []);
    const uiHints = activeChannelSchema.config_ui_hints || {};
    const secretPaths = new Set(activeChannelSchema.secret_paths || []);

    return Object.entries(properties).map(([fieldName, fieldSchema]) => {
      if (['channel_type', 'name', 'enabled'].includes(fieldName)) {
        return null;
      }

      const hint = uiHints[fieldName] || {};
      const isSensitive = Boolean(hint.sensitive) || secretPaths.has(fieldName);
      const isRequired = requiredFields.has(fieldName) && !(editingConfig && isSensitive);
      const formFieldName = CHANNEL_SETTING_FIELDS.has(fieldName)
        ? fieldName
        : ['extra_settings', fieldName];
      const label = hint.label || fieldSchema?.title || humanizeFieldName(fieldName);
      const placeholder = hint.placeholder || fieldSchema?.description;
      const rules = isRequired ? [{ required: true, message: `Please enter ${label}` }] : [];

      if (fieldSchema?.type === 'boolean') {
        return (
          <Form.Item key={fieldName} name={formFieldName} label={label} valuePropName="checked">
            <Switch />
          </Form.Item>
        );
      }

      if (fieldSchema?.enum && fieldSchema.enum.length > 0) {
        return (
          <Form.Item key={fieldName} name={formFieldName} label={label} rules={rules}>
            <Select
              options={fieldSchema.enum.map((value) => ({
                label: String(value),
                value,
              }))}
            />
          </Form.Item>
        );
      }

      if (fieldSchema?.type === 'integer' || fieldSchema?.type === 'number') {
        return (
          <Form.Item key={fieldName} name={formFieldName} label={label} rules={rules}>
            <InputNumber
              style={{ width: '100%' }}
              min={fieldSchema.minimum}
              max={fieldSchema.maximum}
              placeholder={placeholder}
            />
          </Form.Item>
        );
      }

      return (
        <Form.Item key={fieldName} name={formFieldName} label={label} rules={rules}>
          {isSensitive ? (
            <Input.Password
              placeholder={
                editingConfig
                  ? `Leave unchanged to keep existing secret (${SECRET_UNCHANGED_SENTINEL})`
                  : placeholder
              }
            />
          ) : (
            <Input placeholder={placeholder} />
          )}
        </Form.Item>
      );
    });
  }, [activeChannelSchema, editingConfig]);

  return (
    <div style={{ padding: 24 }}>
      <Card
        style={{ marginBottom: 16 }}
        title={
          <Space>
            <MessageOutlined />
            <Title level={4} style={{ margin: 0 }}>
              Plugin Hub
            </Title>
          </Space>
        }
        extra={
          <Space>
            <Input
              placeholder="my-plugin-package==0.1.0"
              value={installRequirement}
              onChange={(event) => { setInstallRequirement(event.target.value); }}
              style={{ width: 280 }}
            />
            <Button
              type="primary"
              loading={pluginActionKey === 'install'}
              onClick={handleInstallPlugin}
            >
              Install
            </Button>
            <Button
              icon={<ReloadOutlined />}
              loading={pluginActionKey === 'reload'}
              onClick={handleReloadPlugins}
            >
              Reload
            </Button>
          </Space>
        }
      >
        <Text type="secondary" style={{ marginBottom: 16, display: 'block' }}>
          Discover, install, enable/disable, and manage channel plugins before creating channel
          configurations.
        </Text>

        {channelPluginCatalog.length > 0 && (
          <Space wrap style={{ marginBottom: 12 }}>
            {channelPluginCatalog.map((entry) => (
              <Tag key={`${entry.plugin_name}:${entry.channel_type}`} color="processing">
                {humanizeChannelType(entry.channel_type)} · {entry.plugin_name}
              </Tag>
            ))}
          </Space>
        )}

        {pluginDiagnostics.length > 0 && (
          <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
            Diagnostics: {pluginDiagnostics.map((item) => item.code).join(', ')}
          </Text>
        )}
        {lastPluginActionDetails?.control_plane_trace && (
          <div
            style={{
              marginBottom: 12,
              border: '1px solid #d9d9d9',
              borderRadius: 8,
              padding: 10,
            }}
          >
            <Space wrap size={[8, 8]}>
              <Tag color="processing">{lastPluginActionDetails.control_plane_trace.action}</Tag>
              <Text code>{lastPluginActionDetails.control_plane_trace.trace_id}</Text>
              {Object.entries(lastPluginActionDetails.control_plane_trace.capability_counts).map(
                ([key, value]) => (
                  <Tag key={key}>{`${key}:${value}`}</Tag>
                )
              )}
              {lastPluginActionDetails.channel_reload_plan && (
                <Text type="secondary">
                  reload:{' '}
                  {Object.entries(lastPluginActionDetails.channel_reload_plan)
                    .map(([key, value]) => `${key}=${value}`)
                    .join(', ')}
                </Text>
              )}
            </Space>
          </div>
        )}

        <Table
          dataSource={plugins}
          columns={pluginColumns}
          rowKey="name"
          loading={pluginsLoading}
          pagination={{ pageSize: 8 }}
        />
      </Card>

      <Card
        title={
          <Space>
            <MessageOutlined />
            <Title level={4} style={{ margin: 0 }}>
              Channel Configurations
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
          Configure IM platform integrations (Feishu, DingTalk, WeCom) to enable AI agent
          communication through chat platforms.
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
        onCancel={() => { setIsModalVisible(false); }}
        onOk={() => { form.submit(); }}
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
          <Form.Item name="channel_type" label="Channel Type" rules={[{ required: true }]}>
            <Select placeholder="Select channel type">
              {channelTypeOptions.map((type) => (
                <Option key={type.value} value={type.value}>
                  <Tag color={type.color}>{type.label}</Tag>
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

          {activeChannelSchema?.schema_supported ? (
            <>
              {schemaLoading && (
                <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
                  Loading plugin schema...
                </Text>
              )}
              {dynamicSchemaFields}
            </>
          ) : (
            <>
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
                rules={
                  editingConfig ? [] : [{ required: true, message: 'Please enter App Secret' }]
                }
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
            </>
          )}

          <Form.Item name="description" label="Description (Optional)">
            <Input.TextArea rows={2} placeholder="Optional description" />
          </Form.Item>

          <Divider>Access Control</Divider>

          <Form.Item name="dm_policy" label="DM Policy">
            <Select>
              {POLICY_OPTIONS.map((opt) => (
                <Option key={opt.value} value={opt.value}>
                  {opt.label}
                </Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item name="group_policy" label="Group Policy">
            <Select>
              {POLICY_OPTIONS.map((opt) => (
                <Option key={opt.value} value={opt.value}>
                  {opt.label}
                </Option>
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
