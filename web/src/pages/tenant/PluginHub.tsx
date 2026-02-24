import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useParams, useSearchParams } from 'react-router-dom';

import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  Badge,
  Button,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import { Package } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useProjectStore } from '@/stores/project';
import { useTenantStore } from '@/stores/tenant';

import { channelService } from '@/services/channelService';

import type {
  ChannelConfig,
  ChannelPluginCatalogItem,
  ChannelPluginConfigSchema,
  CreateChannelConfig,
  PluginActionDetails,
  PluginActionResponse,
  PluginDiagnostic,
  RuntimePlugin,
  UpdateChannelConfig,
} from '@/types/channel';
import type { Project } from '@/types/memory';

const { Title, Text } = Typography;

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

interface PluginActionTimelineEntry {
  id: string;
  action: string;
  message: string;
  success: boolean;
  timestamp: string;
  details: PluginActionDetails | null;
}

export const PluginHub: React.FC = () => {
  const { tenantId: urlTenantId } = useParams<{ tenantId?: string }>();
  const [searchParams] = useSearchParams();
  const projectIdFromQuery = searchParams.get('projectId');
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const tenantId = urlTenantId || currentTenant?.id || null;

  const {
    projects,
    isLoading: projectLoading,
    listProjects,
  } = useProjectStore(
    useShallow((state) => ({
      projects: state.projects,
      isLoading: state.isLoading,
      listProjects: state.listProjects,
    }))
  );

  const [form] = Form.useForm<Record<string, unknown>>();
  const selectedChannelType = Form.useWatch('channel_type', form);

  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [plugins, setPlugins] = useState<RuntimePlugin[]>([]);
  const [pluginDiagnostics, setPluginDiagnostics] = useState<PluginDiagnostic[]>([]);
  const [channelPluginCatalog, setChannelPluginCatalog] = useState<ChannelPluginCatalogItem[]>([]);
  const [channelConfigs, setChannelConfigs] = useState<ChannelConfig[]>([]);
  const [channelSchemas, setChannelSchemas] = useState<Record<string, ChannelPluginConfigSchema>>(
    {}
  );

  const [pluginsLoading, setPluginsLoading] = useState(false);
  const [configsLoading, setConfigsLoading] = useState(false);
  const [schemaLoading, setSchemaLoading] = useState(false);

  const [pluginActionKey, setPluginActionKey] = useState<string | null>(null);
  const [configActionKey, setConfigActionKey] = useState<string | null>(null);
  const [installRequirement, setInstallRequirement] = useState('');
  const [lastPluginActionDetails, setLastPluginActionDetails] =
    useState<PluginActionDetails | null>(null);
  const [pluginActionTimeline, setPluginActionTimeline] = useState<PluginActionTimelineEntry[]>([]);
  const [configModalVisible, setConfigModalVisible] = useState(false);
  const [editingConfig, setEditingConfig] = useState<ChannelConfig | null>(null);

  const recordPluginAction = useCallback((response: PluginActionResponse, fallbackAction: string) => {
    const details = response.details || null;
    setLastPluginActionDetails(details);
    const controlPlaneTrace = details?.control_plane_trace;
    const timestamp = controlPlaneTrace?.timestamp || new Date().toISOString();
    const traceId = controlPlaneTrace?.trace_id;
    const action = controlPlaneTrace?.action || fallbackAction;
    const entry: PluginActionTimelineEntry = {
      id: traceId || `${timestamp}:${action}`,
      action,
      message: response.message,
      success: response.success,
      timestamp,
      details,
    };
    setPluginActionTimeline((prev) => [entry, ...prev].slice(0, 10));
  }, []);

  useEffect(() => {
    if (!tenantId) return;
    listProjects(tenantId).catch(() => {
      message.error('Failed to load projects');
    });
  }, [listProjects, tenantId]);

  useEffect(() => {
    if (projects.length === 0) {
      setSelectedProjectId(null);
      return;
    }

    if (projectIdFromQuery && projects.some((project) => project.id === projectIdFromQuery)) {
      setSelectedProjectId(projectIdFromQuery);
      return;
    }

    setSelectedProjectId((prev) => {
      if (prev && projects.some((project) => project.id === prev)) {
        return prev;
      }
      return projects[0]?.id ?? prev;
    });
  }, [projectIdFromQuery, projects]);

  const loadPluginRuntime = useCallback(async () => {
    if (!tenantId) return;

    setPluginsLoading(true);
    try {
      const [pluginRes, catalogRes] = await Promise.all([
        channelService.listTenantPlugins(tenantId),
        channelService.listTenantChannelPluginCatalog(tenantId),
      ]);
      setPlugins(pluginRes.items);
      setPluginDiagnostics(pluginRes.diagnostics);
      setChannelPluginCatalog(catalogRes.items);
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Failed to load plugin runtime');
    } finally {
      setPluginsLoading(false);
    }
  }, [tenantId]);

  const loadChannelConfigs = useCallback(async () => {
    if (!selectedProjectId) {
      setChannelConfigs([]);
      return;
    }
    setConfigsLoading(true);
    try {
      const items = await channelService.listConfigs(selectedProjectId);
      setChannelConfigs(items);
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : 'Failed to load channel configurations'
      );
    } finally {
      setConfigsLoading(false);
    }
  }, [selectedProjectId]);

  const loadChannelSchema = useCallback(
    async (channelType: string) => {
      if (!tenantId || !channelType) return;
      if (channelSchemas[channelType]) return;
      const catalogEntry = channelPluginCatalog.find((item) => item.channel_type === channelType);
      if (!catalogEntry?.schema_supported) return;

      setSchemaLoading(true);
      try {
        const schema = await channelService.getTenantChannelPluginSchema(tenantId, channelType);
        setChannelSchemas((prev) => ({ ...prev, [channelType]: schema }));
      } catch (error) {
        message.error(error instanceof Error ? error.message : 'Failed to load plugin schema');
      } finally {
        setSchemaLoading(false);
      }
    },
    [channelPluginCatalog, channelSchemas, tenantId]
  );

  useEffect(() => {
    if (!tenantId) {
      setPlugins([]);
      setPluginDiagnostics([]);
      setChannelPluginCatalog([]);
      return;
    }
    void loadPluginRuntime();
  }, [loadPluginRuntime, tenantId]);

  useEffect(() => {
    void loadChannelConfigs();
  }, [loadChannelConfigs]);

  useEffect(() => {
    if (!configModalVisible || !selectedChannelType) return;
    void loadChannelSchema(String(selectedChannelType));
  }, [configModalVisible, loadChannelSchema, selectedChannelType]);

  const activeChannelSchema = selectedChannelType
    ? channelSchemas[String(selectedChannelType)]
    : undefined;

  useEffect(() => {
    if (!configModalVisible || editingConfig || !activeChannelSchema?.defaults) return;
    const defaults = activeChannelSchema.defaults;
    if (!defaults || typeof defaults !== 'object') return;

    const currentValues = form.getFieldsValue(true);
    const nextValues: Record<string, any> = {};
    const currentExtraSettings =
      currentValues.extra_settings && typeof currentValues.extra_settings === 'object'
        ? { ...(currentValues.extra_settings as Record<string, any>) }
        : {};

    Object.entries(defaults).forEach(([key, value]) => {
      if (CHANNEL_SETTING_FIELDS.has(key)) {
        const current = currentValues[key];
        if (current === undefined || current === null || current === '') {
          nextValues[key] = value;
        }
      } else if (currentExtraSettings[key] === undefined) {
        currentExtraSettings[key] = value;
      }
    });

    if (Object.keys(currentExtraSettings).length > 0) {
      nextValues.extra_settings = currentExtraSettings;
    }
    form.setFieldsValue(nextValues);
  }, [activeChannelSchema, configModalVisible, editingConfig, form]);

  const projectOptions = useMemo(
    () =>
      projects.map((project: Project) => ({
        label: project.name,
        value: project.id,
      })),
    [projects]
  );

  const channelTypeOptions = useMemo(() => {
    const optionMap = new Map<string, { value: string; label: string; color: string }>();
    channelPluginCatalog.forEach((entry) => {
      optionMap.set(entry.channel_type, {
        value: entry.channel_type,
        label: humanizeChannelType(entry.channel_type),
        color: entry.schema_supported ? 'processing' : 'default',
      });
    });
    channelConfigs.forEach((config) => {
      if (!optionMap.has(config.channel_type)) {
        optionMap.set(config.channel_type, {
          value: config.channel_type,
          label: humanizeChannelType(config.channel_type),
          color: 'default',
        });
      }
    });
    if (optionMap.size === 0) {
      optionMap.set('feishu', {
        value: 'feishu',
        label: humanizeChannelType('feishu'),
        color: 'processing',
      });
    }
    return Array.from(optionMap.values());
  }, [channelConfigs, channelPluginCatalog]);

  const channelTypeOptionMap = useMemo(
    () => Object.fromEntries(channelTypeOptions.map((item) => [item.value, item])),
    [channelTypeOptions]
  );

  const handleInstallPlugin = useCallback(async () => {
    if (!tenantId) return;
    if (!installRequirement.trim()) {
      message.warning('Please enter a plugin requirement');
      return;
    }
    setPluginActionKey('install');
    try {
      const response = await channelService.installTenantPlugin(
        tenantId,
        installRequirement.trim()
      );
      recordPluginAction(response, 'install');
      message.success(response.message);
      setInstallRequirement('');
      await loadPluginRuntime();
      await loadChannelConfigs();
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Plugin install failed');
    } finally {
      setPluginActionKey(null);
    }
  }, [installRequirement, loadChannelConfigs, loadPluginRuntime, recordPluginAction, tenantId]);

  const handleTogglePlugin = useCallback(
    async (plugin: RuntimePlugin, enabled: boolean) => {
      if (!tenantId) return;
      setPluginActionKey(`${plugin.name}:${enabled ? 'enable' : 'disable'}`);
      try {
        const response = enabled
          ? await channelService.enableTenantPlugin(tenantId, plugin.name)
          : await channelService.disableTenantPlugin(tenantId, plugin.name);
        recordPluginAction(response, enabled ? 'enable' : 'disable');
        if (enabled) {
          message.success(`Plugin enabled: ${plugin.name}`);
        } else {
          message.success(`Plugin disabled: ${plugin.name}`);
        }
        await loadPluginRuntime();
        await loadChannelConfigs();
      } catch (error) {
        message.error(error instanceof Error ? error.message : 'Plugin action failed');
      } finally {
        setPluginActionKey(null);
      }
    },
    [loadChannelConfigs, loadPluginRuntime, recordPluginAction, tenantId]
  );

  const handleReloadPlugins = useCallback(async () => {
    if (!tenantId) return;
    setPluginActionKey('reload');
    try {
      const response = await channelService.reloadTenantPlugins(tenantId);
      recordPluginAction(response, 'reload');
      message.success(response.message);
      await loadPluginRuntime();
      await loadChannelConfigs();
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Plugin reload failed');
    } finally {
      setPluginActionKey(null);
    }
  }, [loadChannelConfigs, loadPluginRuntime, recordPluginAction, tenantId]);

  const handleUninstallPlugin = useCallback(
    async (plugin: RuntimePlugin) => {
      if (!tenantId) return;
      setPluginActionKey(`${plugin.name}:uninstall`);
      try {
        const response = await channelService.uninstallTenantPlugin(tenantId, plugin.name);
        recordPluginAction(response, 'uninstall');
        message.success(response.message);
        await loadPluginRuntime();
        await loadChannelConfigs();
      } catch (error) {
        message.error(error instanceof Error ? error.message : 'Plugin uninstall failed');
      } finally {
        setPluginActionKey(null);
      }
    },
    [loadChannelConfigs, loadPluginRuntime, recordPluginAction, tenantId]
  );

  const handleAddConfig = useCallback(() => {
    if (!selectedProjectId) {
      message.warning('Select a project first');
      return;
    }
    const defaultChannelType = channelTypeOptions[0]?.value || 'feishu';
    setEditingConfig(null);
    form.resetFields();
    form.setFieldsValue({
      channel_type: defaultChannelType,
      enabled: true,
      connection_mode: 'websocket',
    });
    setConfigModalVisible(true);
    void loadChannelSchema(defaultChannelType);
  }, [channelTypeOptions, form, loadChannelSchema, selectedProjectId]);

  const handleEditConfig = useCallback(
    (config: ChannelConfig) => {
      setEditingConfig(config);
      const normalizedExtraSettings =
        config.extra_settings && typeof config.extra_settings === 'object'
          ? Object.fromEntries(
              Object.entries(config.extra_settings).map(([key, value]) => [
                key,
                value === SECRET_UNCHANGED_SENTINEL ? undefined : value,
              ])
            )
          : {};

      form.resetFields();
      form.setFieldsValue({
        ...config,
        app_secret: undefined,
        encrypt_key: undefined,
        verification_token: undefined,
        extra_settings: normalizedExtraSettings,
      });
      setConfigModalVisible(true);
      void loadChannelSchema(config.channel_type);
    },
    [form, loadChannelSchema]
  );

  const handleDeleteConfig = useCallback(
    async (configId: string) => {
      setConfigActionKey(`delete:${configId}`);
      try {
        await channelService.deleteConfig(configId);
        message.success('Configuration deleted');
        await loadChannelConfigs();
      } catch (error) {
        message.error(error instanceof Error ? error.message : 'Failed to delete configuration');
      } finally {
        setConfigActionKey(null);
      }
    },
    [loadChannelConfigs]
  );

  const handleTestConfig = useCallback(
    async (configId: string) => {
      setConfigActionKey(`test:${configId}`);
      try {
        const result = await channelService.testConfig(configId);
        if (result.success) {
          message.success(result.message);
        } else {
          message.error(result.message);
        }
        await loadChannelConfigs();
      } catch (error) {
        message.error(error instanceof Error ? error.message : 'Failed to test configuration');
      } finally {
        setConfigActionKey(null);
      }
    },
    [loadChannelConfigs]
  );

  const handleSaveConfig = useCallback(async () => {
    if (!selectedProjectId) {
      message.warning('Select a project first');
      return;
    }
    try {
      const values = await form.validateFields();
      const payload: Partial<CreateChannelConfig & UpdateChannelConfig> = { ...values };
      const mutablePayload = payload as Record<string, unknown>;
      const extraSettings =
        mutablePayload.extra_settings && typeof mutablePayload.extra_settings === 'object'
          ? { ...(mutablePayload.extra_settings as Record<string, unknown>) }
          : undefined;

      if (activeChannelSchema?.schema_supported) {
        const secretPaths = activeChannelSchema.secret_paths || [];
        secretPaths.forEach((path) => {
          if (CHANNEL_SETTING_FIELDS.has(path)) {
            if (editingConfig && (mutablePayload[path] === undefined || mutablePayload[path] === '')) {
              delete mutablePayload[path];
            }
          } else if (extraSettings && editingConfig) {
            if (extraSettings[path] === undefined || extraSettings[path] === '') {
              delete extraSettings[path];
            }
          }
        });
      } else if (editingConfig) {
        ['app_secret', 'encrypt_key', 'verification_token'].forEach((path) => {
          if (mutablePayload[path] === undefined || mutablePayload[path] === '') {
            delete mutablePayload[path];
          }
        });
      }

      if (extraSettings) {
        Object.keys(extraSettings).forEach((key) => {
          if (
            extraSettings[key] === undefined ||
            extraSettings[key] === '' ||
            extraSettings[key] === SECRET_UNCHANGED_SENTINEL
          ) {
            delete extraSettings[key];
          }
        });
      }
      payload.extra_settings =
        extraSettings && Object.keys(extraSettings).length > 0 ? extraSettings : undefined;

      Object.keys(mutablePayload).forEach((key) => {
        if (mutablePayload[key] === undefined) {
          delete mutablePayload[key];
        }
      });

      setConfigActionKey('save');
      if (editingConfig) {
        const updatePayload = { ...payload } as UpdateChannelConfig & { channel_type?: string };
        delete updatePayload.channel_type;
        await channelService.updateConfig(editingConfig.id, updatePayload);
        message.success('Configuration updated');
      } else {
        const channelType = payload.channel_type;
        const channelName = payload.name;
        if (!channelType || !channelName) {
          message.error('Channel type and name are required');
          return;
        }
        await channelService.createConfig(selectedProjectId, {
          ...payload,
          channel_type: channelType,
          name: channelName,
        });
        message.success('Configuration created');
      }

      setConfigModalVisible(false);
      setEditingConfig(null);
      form.resetFields();
      await loadChannelConfigs();
    } catch (error) {
      if (error instanceof Error) {
        message.error(error.message);
      }
    } finally {
      setConfigActionKey((current) => (current === 'save' ? null : current));
    }
  }, [activeChannelSchema, editingConfig, form, loadChannelConfigs, selectedProjectId]);

  const dynamicSchemaFields = useMemo(() => {
    if (!activeChannelSchema?.schema_supported) return [];
    const properties = activeChannelSchema.config_schema?.properties || {};
    const required = new Set(activeChannelSchema.config_schema?.required || []);
    const hints = activeChannelSchema.config_ui_hints || {};
    const secretPaths = new Set(activeChannelSchema.secret_paths || []);

    return Object.entries(properties)
      .map(([fieldName, schema]) => {
        if (['channel_type', 'name', 'enabled'].includes(fieldName)) {
          return null;
        }
        const hint = hints[fieldName] || {};
        const sensitive = Boolean(hint.sensitive) || secretPaths.has(fieldName);
        const requiredField = required.has(fieldName) && !(editingConfig && sensitive);
        const formName = CHANNEL_SETTING_FIELDS.has(fieldName)
          ? fieldName
          : ['extra_settings', fieldName];
        const label = hint.label || schema.title || humanizeFieldName(fieldName);
        const placeholder = hint.placeholder || schema.description;
        const rules = requiredField
          ? [{ required: true, message: `Please enter ${label}` }]
          : undefined;

        if (schema.type === 'boolean') {
          return (
            <Form.Item key={fieldName} name={formName} label={label} valuePropName="checked">
              <Switch />
            </Form.Item>
          );
        }

        if (schema.enum && schema.enum.length > 0) {
          return (
            <Form.Item key={fieldName} name={formName} label={label} rules={rules}>
              <Select
                options={schema.enum.map((value) => ({
                  value,
                  label: String(value),
                }))}
              />
            </Form.Item>
          );
        }

        if (schema.type === 'integer' || schema.type === 'number') {
          return (
            <Form.Item key={fieldName} name={formName} label={label} rules={rules}>
              <InputNumber
                style={{ width: '100%' }}
                min={schema.minimum}
                max={schema.maximum}
                placeholder={placeholder}
              />
            </Form.Item>
          );
        }

        return (
          <Form.Item key={fieldName} name={formName} label={label} rules={rules}>
            {sensitive ? (
              <Input.Password
                placeholder={
                  editingConfig
                    ? `Leave blank to keep unchanged (${SECRET_UNCHANGED_SENTINEL})`
                    : placeholder
                }
              />
            ) : (
              <Input placeholder={placeholder} />
            )}
          </Form.Item>
        );
      })
      .filter(Boolean);
  }, [activeChannelSchema, editingConfig]);

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
          <Popconfirm
            title={`Uninstall plugin ${record.name}?`}
            description="This only supports package-managed plugins."
            onConfirm={() => handleUninstallPlugin(record)}
            okText="Uninstall"
            okButtonProps={{ danger: true }}
            disabled={!record.package}
          >
            <Button
              size="small"
              danger
              disabled={!record.package}
              loading={pluginActionKey === `${record.name}:uninstall`}
            >
              Uninstall
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const configColumns = [
    {
      title: 'Name',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: ChannelConfig) => (
        <Space>
          <Text strong>{name}</Text>
          {record.enabled ? <Tag color="success">Enabled</Tag> : <Tag>Disabled</Tag>}
        </Space>
      ),
    },
    {
      title: 'Type',
      dataIndex: 'channel_type',
      key: 'channel_type',
      render: (channelType: string) => {
        const option = channelTypeOptionMap[channelType];
        return (
          <Tag color={option?.color || 'default'}>
            {option?.label || humanizeChannelType(channelType)}
          </Tag>
        );
      },
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        if (status === 'connected') return <Badge status="success" text="Connected" />;
        if (status === 'error') return <Badge status="error" text="Error" />;
        if (status === 'circuit_open') return <Badge color="orange" text="Circuit Open" />;
        return <Badge status="default" text="Disconnected" />;
      },
    },
    {
      title: 'Actions',
      key: 'actions',
      render: (_: unknown, record: ChannelConfig) => (
        <Space>
          <Button
            size="small"
            icon={<ReloadOutlined />}
            loading={configActionKey === `test:${record.id}`}
            onClick={() => handleTestConfig(record.id)}
          />
          <Button size="small" icon={<EditOutlined />} onClick={() => { handleEditConfig(record); }} />
          <Popconfirm
            title="Delete configuration?"
            onConfirm={() => handleDeleteConfig(record.id)}
            okText="Delete"
            okButtonProps={{ danger: true }}
          >
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              loading={configActionKey === `delete:${record.id}`}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  if (!tenantId) {
    return (
      <div className="max-w-full mx-auto w-full h-full flex items-center justify-center">
        <Empty description="Missing tenant context" />
      </div>
    );
  }

  return (
    <div className="max-w-full mx-auto w-full h-full p-4 md:p-6 space-y-4">
      <section className="bg-white dark:bg-surface-dark rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm p-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
              <Package size={20} className="text-primary" />
            </div>
            <div>
              <Title level={4} style={{ margin: 0 }}>
                Plugin Hub
              </Title>
              <Text type="secondary">
                Manage plugins and configure channel instances from one tenant-level workspace.
              </Text>
            </div>
          </div>

          <Space wrap>
            <Select
              style={{ minWidth: 240 }}
              placeholder="Select project context for channel configs"
              value={selectedProjectId || undefined}
              options={projectOptions}
              onChange={(value) => { setSelectedProjectId(value); }}
              loading={projectLoading}
            />
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
        </div>
      </section>

      <section className="bg-white dark:bg-surface-dark rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div className="px-5 pt-5 pb-2">
          <Title level={5} style={{ margin: 0 }}>
            Runtime Plugins
          </Title>
        </div>
        <div className="px-5 pb-5">
          {lastPluginActionDetails?.control_plane_trace && (
            <div className="mb-4 rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-2">
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
          {pluginActionTimeline.length > 0 && (
            <div className="mb-4 rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-2">
              <div className="text-xs font-medium text-slate-600 dark:text-slate-300">
                Operation Timeline
              </div>
              <div className="mt-2 space-y-2">
                {pluginActionTimeline.map((entry) => (
                  <div
                    key={entry.id}
                    className="rounded-md border border-slate-100 dark:border-slate-800 px-2 py-1.5"
                  >
                    <Space wrap size={[6, 6]}>
                      <Tag color={entry.success ? 'success' : 'error'}>{entry.action}</Tag>
                      {entry.details?.control_plane_trace?.trace_id ? (
                        <Text code>{entry.details.control_plane_trace.trace_id}</Text>
                      ) : null}
                      <Text type="secondary">{new Date(entry.timestamp).toLocaleString()}</Text>
                      <Text>{entry.message}</Text>
                    </Space>
                    {entry.details?.channel_reload_plan ? (
                      <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        reload:{' '}
                        {Object.entries(entry.details.channel_reload_plan)
                          .map(([key, value]) => `${key}=${value}`)
                          .join(', ')}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          )}
          <Table
            dataSource={plugins}
            columns={pluginColumns}
            rowKey="name"
            loading={pluginsLoading}
            pagination={{ pageSize: 8 }}
          />
        </div>
      </section>

      <section className="bg-white dark:bg-surface-dark rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div className="px-5 pt-5 pb-2 flex items-center justify-between">
          <Title level={5} style={{ margin: 0 }}>
            Channel Configurations
          </Title>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleAddConfig}
            disabled={!selectedProjectId}
          >
            Add Channel
          </Button>
        </div>
        <div className="px-5 pb-5">
          {selectedProjectId ? (
            <Table
              dataSource={channelConfigs}
              columns={configColumns}
              rowKey="id"
              loading={configsLoading}
              pagination={{ pageSize: 8 }}
            />
          ) : (
            <Empty description="Select a project to configure channels" />
          )}
        </div>
      </section>

      <section className="bg-white dark:bg-surface-dark rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm p-5">
        <Title level={5} style={{ marginTop: 0 }}>
          Channel Catalog & Diagnostics
        </Title>
        {channelPluginCatalog.length > 0 ? (
          <Space wrap>
            {channelPluginCatalog.map((entry) => (
              <Tag key={`${entry.plugin_name}:${entry.channel_type}`} color="processing">
                {humanizeChannelType(entry.channel_type)} · {entry.plugin_name}
                {entry.schema_supported ? ' · schema' : ''}
              </Tag>
            ))}
          </Space>
        ) : (
          <Text type="secondary">No channel adapters discovered.</Text>
        )}

        {pluginDiagnostics.length > 0 && (
          <div className="mt-4 space-y-2">
            {pluginDiagnostics.map((item) => (
              <div
                key={`${item.plugin_name}:${item.code}:${item.message}`}
                className="rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-2"
              >
                <Space wrap>
                  <Tag
                    color={
                      item.level === 'error'
                        ? 'error'
                        : item.level === 'warning'
                          ? 'warning'
                          : 'default'
                    }
                  >
                    {item.level}
                  </Tag>
                  <Text strong>{item.plugin_name}</Text>
                  <Text code>{item.code}</Text>
                </Space>
                <div>
                  <Text type="secondary">{item.message}</Text>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <Modal
        open={configModalVisible}
        title={editingConfig ? 'Edit Channel Configuration' : 'Add Channel Configuration'}
        onCancel={() => {
          setConfigModalVisible(false);
          setEditingConfig(null);
          form.resetFields();
        }}
        onOk={handleSaveConfig}
        confirmLoading={configActionKey === 'save'}
        width={760}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="channel_type" label="Channel Type" rules={[{ required: true }]}>
            <Select
              options={channelTypeOptions.map((option) => ({
                value: option.value,
                label: option.label,
              }))}
            />
          </Form.Item>

          <Form.Item
            name="name"
            label="Name"
            rules={[{ required: true, message: 'Please enter a name' }]}
          >
            <Input placeholder="e.g., Feishu Bot for Support" />
          </Form.Item>

          <Form.Item name="enabled" label="Enabled" valuePropName="checked">
            <Switch />
          </Form.Item>

          {activeChannelSchema?.schema_supported ? (
            <>
              {schemaLoading && (
                <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
                  Loading schema...
                </Text>
              )}
              {dynamicSchemaFields}
            </>
          ) : (
            <>
              <Form.Item name="connection_mode" label="Connection Mode">
                <Select
                  options={[
                    { label: 'WebSocket (Recommended)', value: 'websocket' },
                    { label: 'Webhook', value: 'webhook' },
                  ]}
                />
              </Form.Item>

              <Form.Item name="app_id" label="App ID">
                <Input placeholder="cli_xxx" />
              </Form.Item>

              <Form.Item
                name="app_secret"
                label={`App Secret ${editingConfig ? '(leave blank to keep unchanged)' : ''}`}
              >
                <Input.Password placeholder="Enter app secret" />
              </Form.Item>

              <Form.Item name="encrypt_key" label="Encrypt Key">
                <Input.Password placeholder="Optional webhook encrypt key" />
              </Form.Item>

              <Form.Item name="verification_token" label="Verification Token">
                <Input.Password placeholder="Optional webhook verification token" />
              </Form.Item>

              <Form.Item name="webhook_url" label="Webhook URL">
                <Input placeholder="https://your-domain.com/webhook" />
              </Form.Item>

              <Form.Item name="domain" label="Domain">
                <Input placeholder="feishu / lark / custom" />
              </Form.Item>
            </>
          )}

          <Form.Item name="description" label="Description">
            <Input.TextArea rows={2} placeholder="Optional description" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default PluginHub;
