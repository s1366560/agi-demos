import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

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
import { Plus, Pencil, Trash2, RefreshCw, AlertCircle, MessageSquare } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useChannelStore } from '@/stores/channel';

import { channelService } from '@/services/channelService';

import { formatPluginCapabilityCounts } from '@/utils/pluginCapabilityCounts';

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

import type { ColumnsType } from 'antd/es/table';

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
  { value: 'websocket', labelKey: 'project.channelConfig.connectionModeWebsocket' },
  { value: 'webhook', labelKey: 'project.channelConfig.connectionModeWebhook' },
];

const POLICY_OPTIONS = [
  { value: 'open', labelKey: 'project.channelConfig.policy.open' },
  { value: 'allowlist', labelKey: 'project.channelConfig.policy.allowlist' },
  { value: 'disabled', labelKey: 'project.channelConfig.policy.disabled' },
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
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(' ');

const humanizeFieldName = (fieldName: string): string =>
  fieldName
    .split(/[-_]/g)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(' ');

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const ChannelConfigPage: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const { t } = useTranslation();
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [editingConfig, setEditingConfig] = useState<ChannelConfig | null>(null);
  const [form] = Form.useForm<Record<string, unknown>>();
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
  const watchedChannelType: unknown = Form.useWatch('channel_type', form);
  const selectedChannelType =
    typeof watchedChannelType === 'string' ? watchedChannelType : undefined;
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
      message.error(
        error instanceof Error
          ? error.message
          : t('project.channelConfig.errors.failedToLoadPlugins')
      );
    } finally {
      setPluginsLoading(false);
    }
  }, [projectId, t]);

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
        message.error(
          error instanceof Error
            ? error.message
            : t('project.channelConfig.errors.failedToLoadSchema')
        );
      } finally {
        setSchemaLoading(false);
      }
    },
    [channelPluginCatalog, channelSchemas, projectId, t]
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
      void fetchConfigs(projectId);
    }
  }, [projectId, fetchConfigs]);

  useEffect(() => {
    void loadPluginRuntime();
  }, [loadPluginRuntime]);

  useEffect(() => {
    if (!selectedChannelType || !isModalVisible) return;
    void loadChannelSchema(selectedChannelType);
  }, [isModalVisible, loadChannelSchema, selectedChannelType]);

  useEffect(() => {
    if (!isModalVisible || editingConfig || !activeChannelSchema?.defaults) return;
    const defaults = activeChannelSchema.defaults;

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
      const extraSettings = form.getFieldValue('extra_settings') as unknown;
      initialValues.extra_settings = {
        ...(isRecord(extraSettings) ? extraSettings : {}),
        ...initialExtraSettings,
      };
    }
    form.setFieldsValue(initialValues as Parameters<typeof form.setFieldsValue>[0]);
  }, [activeChannelSchema, editingConfig, form, isModalVisible]);

  // Auto-refresh status every 10s
  const intervalRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
  useEffect(() => {
    if (projectId) {
      intervalRef.current = setInterval(() => {
        void fetchConfigs(projectId);
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
        message.success(t('project.channelConfig.messages.configDeleted'));
      } catch (_error) {
        message.error(t('project.channelConfig.messages.failedToDelete'));
      }
    },
    [deleteConfig, t]
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
        message.error(t('project.channelConfig.messages.testFailed'));
      } finally {
        setTestingConfig(null);
      }
    },
    [testConfig, t]
  );

  const handleInstallPlugin = useCallback(async () => {
    if (!projectId) return;
    if (!installRequirement.trim()) {
      message.warning(t('project.channelConfig.messages.enterPluginRequirement'));
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
      message.error(
        error instanceof Error
          ? error.message
          : t('project.channelConfig.messages.pluginInstallFailed')
      );
    } finally {
      setPluginActionKey(null);
    }
  }, [installRequirement, loadPluginRuntime, projectId, t]);

  const handleTogglePlugin = useCallback(
    async (plugin: RuntimePlugin, enabled: boolean) => {
      if (!projectId) return;
      setPluginActionKey(`${plugin.name}:${enabled ? 'enable' : 'disable'}`);
      try {
        const response = enabled
          ? await channelService.enablePlugin(projectId, plugin.name)
          : await channelService.disablePlugin(projectId, plugin.name);
        setLastPluginActionDetails(response.details || null);
        message.success(
          enabled
            ? t('project.channelConfig.messages.pluginEnabled', { name: plugin.name })
            : t('project.channelConfig.messages.pluginDisabled', { name: plugin.name })
        );
        await loadPluginRuntime();
      } catch (error) {
        message.error(
          error instanceof Error
            ? error.message
            : t('project.channelConfig.messages.pluginActionFailed')
        );
      } finally {
        setPluginActionKey(null);
      }
    },
    [loadPluginRuntime, projectId, t]
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
      message.error(
        error instanceof Error
          ? error.message
          : t('project.channelConfig.messages.pluginReloadFailed')
      );
    } finally {
      setPluginActionKey(null);
    }
  }, [loadPluginRuntime, projectId, t]);

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
          message.success(t('project.channelConfig.messages.configUpdated'));
        } else {
          if (!projectId) {
            message.error(t('project.channelConfig.messages.projectIdRequired'));
            return;
          }
          await createConfig(projectId, values as CreateChannelConfig);
          message.success(t('project.channelConfig.messages.configCreated'));
        }
        setIsModalVisible(false);
        form.resetFields();
      } catch (_error) {
        message.error(t('project.channelConfig.messages.failedToSave'));
      }
    },
    [editingConfig, projectId, createConfig, updateConfig, form, t]
  );

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'connected':
        return <Badge status="success" text={t('project.channelConfig.status.connected')} />;
      case 'error':
        return <Badge status="error" text={t('project.channelConfig.status.error')} />;
      case 'circuit_open':
        return <Badge color="orange" text={t('project.channelConfig.status.circuitOpen')} />;
      default:
        return <Badge status="default" text={t('project.channelConfig.status.disconnected')} />;
    }
  };

  const columns: ColumnsType<ChannelConfig> = [
    {
      title: t('project.channelConfig.columns.name'),
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: ChannelConfig) => (
        <Space>
          <Text strong>{text}</Text>
          {record.enabled ? (
            <Tag color="success">{t('project.channelConfig.status.enabled')}</Tag>
          ) : (
            <Tag color="default">{t('project.channelConfig.status.disabled')}</Tag>
          )}
        </Space>
      ),
    },
    {
      title: t('project.channelConfig.columns.type'),
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
      title: t('project.channelConfig.columns.connection'),
      dataIndex: 'connection_mode',
      key: 'connection_mode',
      render: (mode: string) => mode.toUpperCase(),
    },
    {
      title: t('project.channelConfig.columns.status'),
      dataIndex: 'status',
      key: 'status',
      render: getStatusBadge,
    },
    {
      title: t('project.channelConfig.columns.lastError'),
      dataIndex: 'last_error',
      key: 'last_error',
      ellipsis: true,
      render: (error: string | null) =>
        error ? (
          <Tooltip title={error}>
            <AlertCircle size={16} style={{ color: '#ff4d4f' }} />
            <Text type="danger" style={{ marginLeft: 8 }}>
              {error.slice(0, 30)}...
            </Text>
          </Tooltip>
        ) : null,
    },
    {
      title: t('project.channelConfig.columns.created'),
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date: string) => new Date(date).toLocaleDateString(),
    },
    {
      title: t('project.channelConfig.columns.actions'),
      key: 'actions',
      render: (_value: unknown, record: ChannelConfig) => (
        <Space>
          <Tooltip title={t('project.channelConfig.actions.testConnection')}>
            <Button
              icon={<RefreshCw size={16} />}
              size="small"
              loading={testingConfig === record.id}
              onClick={() => {
                void handleTest(record.id);
              }}
            />
          </Tooltip>
          <Tooltip title={t('project.channelConfig.actions.edit')}>
            <Button
              icon={<Pencil size={16} />}
              size="small"
              onClick={() => {
                handleEdit(record);
              }}
            />
          </Tooltip>
          <Popconfirm
            title={t('project.channelConfig.deleteConfirmTitle')}
            description={t('project.channelConfig.deleteConfirmDescription')}
            onConfirm={() => {
              void handleDelete(record.id);
            }}
            okText={t('common.delete')}
            okButtonProps={{ danger: true }}
          >
            <Button icon={<Trash2 size={16} />} size="small" danger />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const pluginColumns: ColumnsType<RuntimePlugin> = [
    {
      title: t('project.channelConfig.columns.plugin'),
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: RuntimePlugin) => (
        <Space orientation="vertical" size={0}>
          <Text strong>{name}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {record.package || t('project.channelConfig.pluginSource.local')}
            {record.version ? `@${record.version}` : ''}
          </Text>
        </Space>
      ),
    },
    {
      title: t('project.channelConfig.columns.source'),
      dataIndex: 'source',
      key: 'source',
      render: (source: string) => <Tag>{source}</Tag>,
    },
    {
      title: t('project.channelConfig.columns.channels'),
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
          <Text type="secondary">{t('project.channelConfig.pluginType.toolOnly')}</Text>
        ),
    },
    {
      title: t('project.channelConfig.columns.status'),
      key: 'status',
      render: (_: unknown, record: RuntimePlugin) =>
        record.enabled ? (
          <Badge status="success" text={t('project.channelConfig.status.enabled')} />
        ) : (
          <Badge status="default" text={t('project.channelConfig.status.disabled')} />
        ),
    },
    {
      title: t('project.channelConfig.columns.actions'),
      key: 'actions',
      render: (_: unknown, record: RuntimePlugin) => (
        <Space>
          {record.enabled ? (
            <Button
              size="small"
              loading={pluginActionKey === `${record.name}:disable`}
              onClick={() => {
                void handleTogglePlugin(record, false);
              }}
            >
              {t('project.channelConfig.actions.disable')}
            </Button>
          ) : (
            <Button
              size="small"
              type="primary"
              ghost
              loading={pluginActionKey === `${record.name}:enable`}
              onClick={() => {
                void handleTogglePlugin(record, true);
              }}
            >
              {t('project.channelConfig.actions.enable')}
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
    const secretPaths = new Set(activeChannelSchema.secret_paths);

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
      const label = hint.label || fieldSchema.title || humanizeFieldName(fieldName);
      const placeholder = hint.placeholder || fieldSchema.description;
      const rules = isRequired
        ? [{ required: true, message: t('project.channelConfig.pleaseEnter', { field: label }) }]
        : [];

      if (fieldSchema.type === 'boolean') {
        return (
          <Form.Item key={fieldName} name={formFieldName} label={label} valuePropName="checked">
            <Switch />
          </Form.Item>
        );
      }

      if (fieldSchema.enum && fieldSchema.enum.length > 0) {
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

      if (fieldSchema.type === 'integer' || fieldSchema.type === 'number') {
        return (
          <Form.Item key={fieldName} name={formFieldName} label={label} rules={rules}>
            <InputNumber
              style={{ width: '100%' }}
              {...(fieldSchema.minimum != null ? { min: fieldSchema.minimum } : {})}
              {...(fieldSchema.maximum != null ? { max: fieldSchema.maximum } : {})}
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
                  ? t('project.channelConfig.leaveUnchanged', {
                      sentinel: SECRET_UNCHANGED_SENTINEL,
                    })
                  : placeholder
              }
            />
          ) : (
            <Input placeholder={placeholder} />
          )}
        </Form.Item>
      );
    });
  }, [activeChannelSchema, editingConfig, t]);

  return (
    <div style={{ padding: 24 }}>
      <Card
        style={{ marginBottom: 16 }}
        title={
          <Space>
            <MessageSquare size={20} />
            <Title level={4} style={{ margin: 0 }}>
              {t('project.channelConfig.pluginHub')}
            </Title>
          </Space>
        }
        extra={
          <Space>
            <Input
              placeholder={t('project.channelConfig.pluginRequirementPlaceholder')}
              value={installRequirement}
              onChange={(event) => {
                setInstallRequirement(event.target.value);
              }}
              style={{ width: 280 }}
            />
            <Button
              type="primary"
              loading={pluginActionKey === 'install'}
              onClick={() => {
                void handleInstallPlugin();
              }}
            >
              {t('project.channelConfig.actions.install')}
            </Button>
            <Button
              icon={<RefreshCw size={16} />}
              loading={pluginActionKey === 'reload'}
              onClick={() => {
                void handleReloadPlugins();
              }}
            >
              {t('project.channelConfig.actions.reload')}
            </Button>
          </Space>
        }
      >
        <Text type="secondary" style={{ marginBottom: 16, display: 'block' }}>
          {t('project.channelConfig.pluginHubDescription')}
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
            {t('project.channelConfig.diagnostics')}:{' '}
            {pluginDiagnostics.map((item) => item.code).join(', ')}
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
              {formatPluginCapabilityCounts(
                lastPluginActionDetails.control_plane_trace.capability_counts
              ).map(({ key, label, value }) => (
                <Tag key={key}>{`${label}: ${String(value)}`}</Tag>
              ))}
              {lastPluginActionDetails.channel_reload_plan && (
                <Text type="secondary">
                  {t('project.channelConfig.reloadPlanLabel')}:{' '}
                  {Object.entries(lastPluginActionDetails.channel_reload_plan)
                    .map(([key, value]) => `${key}=${value.toString()}`)
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
            <MessageSquare size={20} />
            <Title level={4} style={{ margin: 0 }}>
              {t('project.channelConfig.channelConfigurations')}
            </Title>
          </Space>
        }
        extra={
          <Button type="primary" icon={<Plus size={16} />} onClick={handleAdd}>
            {t('project.channelConfig.actions.addChannel')}
          </Button>
        }
      >
        <Text type="secondary" style={{ marginBottom: 16, display: 'block' }}>
          {t('project.channelConfig.channelConfigurationsDescription')}
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
        title={
          editingConfig
            ? t('project.channelConfig.editChannelConfig')
            : t('project.channelConfig.addChannelConfig')
        }
        open={isModalVisible}
        onCancel={() => {
          setIsModalVisible(false);
        }}
        onOk={() => {
          form.submit();
        }}
        width={720}
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={(values) => {
            void handleSubmit(values as CreateChannelConfig | UpdateChannelConfig);
          }}
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
            label={t('project.channelConfig.channelType')}
            rules={[{ required: true }]}
          >
            <Select placeholder={t('project.channelConfig.selectChannelType')}>
              {channelTypeOptions.map((type) => (
                <Option key={type.value} value={type.value}>
                  <Tag color={type.color}>{type.label}</Tag>
                </Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item
            name="name"
            label={t('project.channelConfig.name')}
            rules={[{ required: true, message: t('project.channelConfig.pleaseEnterName') }]}
          >
            <Input placeholder={t('project.channelConfig.configNamePlaceholder')} />
          </Form.Item>

          <Form.Item
            name="enabled"
            label={t('project.channelConfig.status.enabled')}
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>

          {activeChannelSchema?.schema_supported ? (
            <>
              {schemaLoading && (
                <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
                  {t('project.channelConfig.loadingSchema')}
                </Text>
              )}
              {dynamicSchemaFields}
            </>
          ) : (
            <>
              <Form.Item
                name="connection_mode"
                label={t('project.channelConfig.connectionMode')}
                rules={[{ required: true }]}
              >
                <Select>
                  {CONNECTION_MODES.map((mode) => (
                    <Option key={mode.value} value={mode.value}>
                      {t(mode.labelKey)}
                    </Option>
                  ))}
                </Select>
              </Form.Item>

              <Form.Item
                name="app_id"
                label={t('project.channelConfig.appId')}
                rules={[{ required: true, message: t('project.channelConfig.pleaseEnterAppId') }]}
              >
                <Input placeholder="cli_xxx" />
              </Form.Item>

              <Form.Item
                name="app_secret"
                label={
                  editingConfig
                    ? t('project.channelConfig.appSecretKeepUnchanged')
                    : t('project.channelConfig.appSecret')
                }
                rules={
                  editingConfig
                    ? []
                    : [{ required: true, message: t('project.channelConfig.pleaseEnterAppSecret') }]
                }
              >
                <Input.Password placeholder={t('project.channelConfig.enterAppSecret')} />
              </Form.Item>

              <Form.Item name="encrypt_key" label={t('project.channelConfig.encryptKeyOptional')}>
                <Input.Password placeholder={t('project.channelConfig.forWebhookVerification')} />
              </Form.Item>

              <Form.Item
                name="verification_token"
                label={t('project.channelConfig.verificationTokenOptional')}
              >
                <Input.Password placeholder={t('project.channelConfig.forWebhookVerification')} />
              </Form.Item>

              <Form.Item name="webhook_url" label={t('project.channelConfig.webhookUrlOptional')}>
                <Input placeholder="https://your-domain.com/webhook" />
              </Form.Item>

              <Form.Item
                name="domain"
                label={t('project.channelConfig.domainLabel')}
                initialValue="feishu"
              >
                <Select>
                  <Option value="feishu">{t('project.channelConfig.domain.feishuChina')}</Option>
                  <Option value="lark">{t('project.channelConfig.domain.larkIntl')}</Option>
                </Select>
              </Form.Item>
            </>
          )}

          <Form.Item name="description" label={t('project.channelConfig.descriptionOptional')}>
            <Input.TextArea rows={2} placeholder={t('project.channelConfig.optionalDescription')} />
          </Form.Item>

          <Divider>{t('project.channelConfig.accessControl')}</Divider>

          <Form.Item name="dm_policy" label={t('project.channelConfig.dmPolicy')}>
            <Select>
              {POLICY_OPTIONS.map((opt) => (
                <Option key={opt.value} value={opt.value}>
                  {t(opt.labelKey)}
                </Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item name="group_policy" label={t('project.channelConfig.groupPolicy')}>
            <Select>
              {POLICY_OPTIONS.map((opt) => (
                <Option key={opt.value} value={opt.value}>
                  {t(opt.labelKey)}
                </Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item
            name="allow_from"
            label={t('project.channelConfig.dmAllowlist')}
            tooltip={t('project.channelConfig.dmAllowlistTooltip')}
          >
            <Select mode="tags" placeholder={t('project.channelConfig.enterUserIds')} />
          </Form.Item>

          <Form.Item
            name="group_allow_from"
            label={t('project.channelConfig.groupAllowlist')}
            tooltip={t('project.channelConfig.groupAllowlistTooltip')}
          >
            <Select mode="tags" placeholder={t('project.channelConfig.enterGroupChatIds')} />
          </Form.Item>

          <Form.Item
            name="rate_limit_per_minute"
            label={t('project.channelConfig.rateLimit')}
            tooltip={t('project.channelConfig.rateLimitTooltip')}
          >
            <InputNumber min={0} max={1000} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default ChannelConfigPage;
