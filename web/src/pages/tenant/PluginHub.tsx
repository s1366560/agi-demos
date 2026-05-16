import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useSearchParams } from 'react-router-dom';

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
import { Package, Trash2, Pencil, Plus, RefreshCw } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useProjectStore } from '@/stores/project';
import { useTenantStore } from '@/stores/tenant';

import { channelService } from '@/services/channelService';

import { formatPluginCapabilityCounts } from '@/utils/pluginCapabilityCounts';

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

const removeUndefinedValues = (record: Record<string, unknown>): Record<string, unknown> =>
  Object.fromEntries(Object.entries(record).filter(([, value]) => value !== undefined));

const removeEmptySecretValues = (
  record: Record<string, unknown>,
  secretPaths: Set<string>,
  isSecretKey: (key: string) => boolean
): Record<string, unknown> =>
  Object.fromEntries(
    Object.entries(record).filter(
      ([key, value]) =>
        !(secretPaths.has(key) && isSecretKey(key) && (value === undefined || value === ''))
    )
  );

const sanitizeExtraSettings = (
  extraSettings: Record<string, unknown> | undefined,
  secretPaths: Set<string>,
  editingConfig: ChannelConfig | null
): Record<string, unknown> | undefined => {
  if (!extraSettings) return undefined;

  const sanitized = Object.fromEntries(
    Object.entries(extraSettings).filter(([key, value]) => {
      if (value === undefined || value === '' || value === SECRET_UNCHANGED_SENTINEL) {
        return false;
      }
      return !(editingConfig && secretPaths.has(key) && value === '');
    })
  );

  return Object.keys(sanitized).length > 0 ? sanitized : undefined;
};

interface PluginActionTimelineEntry {
  id: string;
  action: string;
  message: string;
  success: boolean;
  timestamp: string;
  details: PluginActionDetails | null;
}

export const PluginHub: React.FC = () => {
  const { tenantId: urlTenantId } = useParams<{ tenantId?: string | undefined }>();
  const { t } = useTranslation();
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
  const watchedChannelType: unknown = Form.useWatch('channel_type', form);
  const selectedChannelType =
    typeof watchedChannelType === 'string' ? watchedChannelType : undefined;

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

  const recordPluginAction = useCallback(
    (response: PluginActionResponse, fallbackAction: string) => {
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
    },
    []
  );

  useEffect(() => {
    if (!tenantId) return;
    listProjects(tenantId).catch(() => {
      message.error(t('tenant.pluginHub.messages.loadProjectsFailed'));
    });
  }, [listProjects, tenantId, t]);

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
      message.error(
        error instanceof Error ? error.message : t('tenant.pluginHub.messages.loadPluginsFailed')
      );
    } finally {
      setPluginsLoading(false);
    }
  }, [tenantId, t]);

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
        error instanceof Error ? error.message : t('tenant.pluginHub.channelsList.loadFailed')
      );
    } finally {
      setConfigsLoading(false);
    }
  }, [selectedProjectId, t]);

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
        message.error(
          error instanceof Error ? error.message : t('tenant.pluginHub.messages.loadSchemaFailed')
        );
      } finally {
        setSchemaLoading(false);
      }
    },
    [channelPluginCatalog, channelSchemas, tenantId, t]
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
    void loadChannelSchema(selectedChannelType);
  }, [configModalVisible, loadChannelSchema, selectedChannelType]);

  const activeChannelSchema = selectedChannelType ? channelSchemas[selectedChannelType] : undefined;

  useEffect(() => {
    if (!configModalVisible || editingConfig || !activeChannelSchema?.defaults) return;
    const defaults = activeChannelSchema.defaults;

    const currentValues = form.getFieldsValue(true) as Record<string, unknown>;
    const nextValues: Record<string, unknown> = {};
    const currentExtraSettings = isRecord(currentValues.extra_settings)
      ? { ...currentValues.extra_settings }
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
    form.setFieldsValue(nextValues as Parameters<typeof form.setFieldsValue>[0]);
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
      message.warning(t('tenant.pluginHub.messages.enterPluginRequirement'));
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
      message.error(
        error instanceof Error ? error.message : t('tenant.pluginHub.messages.pluginInstallFailed')
      );
    } finally {
      setPluginActionKey(null);
    }
  }, [installRequirement, loadChannelConfigs, loadPluginRuntime, recordPluginAction, tenantId, t]);

  const handleTogglePlugin = useCallback(
    async (plugin: RuntimePlugin, enabled: boolean) => {
      if (!tenantId) return;
      setPluginActionKey(`${plugin.name}:${enabled ? 'enable' : 'disable'}`);
      try {
        const response = enabled
          ? await channelService.enableTenantPlugin(tenantId, plugin.name)
          : await channelService.disableTenantPlugin(tenantId, plugin.name);
        recordPluginAction(response, enabled ? 'enable' : 'disable');
        message.success(
          enabled
            ? t('tenant.pluginHub.messages.pluginEnabled', { name: plugin.name })
            : t('tenant.pluginHub.messages.pluginDisabled', { name: plugin.name })
        );
        await loadPluginRuntime();
        await loadChannelConfigs();
      } catch (error) {
        message.error(
          error instanceof Error ? error.message : t('tenant.pluginHub.messages.pluginActionFailed')
        );
      } finally {
        setPluginActionKey(null);
      }
    },
    [loadChannelConfigs, loadPluginRuntime, recordPluginAction, tenantId, t]
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
      message.error(
        error instanceof Error ? error.message : t('tenant.pluginHub.messages.pluginReloadFailed')
      );
    } finally {
      setPluginActionKey(null);
    }
  }, [loadChannelConfigs, loadPluginRuntime, recordPluginAction, tenantId, t]);

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
        message.error(
          error instanceof Error
            ? error.message
            : t('tenant.pluginHub.messages.pluginUninstallFailed')
        );
      } finally {
        setPluginActionKey(null);
      }
    },
    [loadChannelConfigs, loadPluginRuntime, recordPluginAction, tenantId, t]
  );

  const handleAddConfig = useCallback(() => {
    if (!selectedProjectId) {
      message.warning(t('tenant.pluginHub.messages.selectProjectFirst'));
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
  }, [channelTypeOptions, form, loadChannelSchema, selectedProjectId, t]);

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
        message.success(t('tenant.pluginHub.channelsList.deleteSuccess'));
        await loadChannelConfigs();
      } catch (error) {
        message.error(
          error instanceof Error ? error.message : t('tenant.pluginHub.channelsList.deleteFailed')
        );
      } finally {
        setConfigActionKey(null);
      }
    },
    [loadChannelConfigs, t]
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
        message.error(
          error instanceof Error ? error.message : t('tenant.pluginHub.channelsList.testFailed')
        );
      } finally {
        setConfigActionKey(null);
      }
    },
    [loadChannelConfigs, t]
  );

  const handleSaveConfig = useCallback(async () => {
    if (!selectedProjectId) {
      message.warning(t('tenant.pluginHub.messages.selectProjectFirst'));
      return;
    }
    try {
      const values = await form.validateFields();
      let mutablePayload: Record<string, unknown> = { ...values };
      const schemaSecretPaths =
        activeChannelSchema?.schema_supported === true
          ? new Set(activeChannelSchema.secret_paths)
          : new Set<string>();
      const fallbackSecretPaths = new Set(['app_secret', 'encrypt_key', 'verification_token']);
      let extraSettings = isRecord(mutablePayload.extra_settings)
        ? { ...mutablePayload.extra_settings }
        : undefined;

      if (activeChannelSchema?.schema_supported) {
        mutablePayload = editingConfig
          ? removeEmptySecretValues(mutablePayload, schemaSecretPaths, (key) =>
              CHANNEL_SETTING_FIELDS.has(key)
            )
          : mutablePayload;
      } else if (editingConfig) {
        mutablePayload = removeEmptySecretValues(mutablePayload, fallbackSecretPaths, () => true);
      }

      extraSettings = sanitizeExtraSettings(extraSettings, schemaSecretPaths, editingConfig);
      mutablePayload = removeUndefinedValues({
        ...mutablePayload,
        extra_settings: extraSettings,
      });
      const payload = mutablePayload as Partial<CreateChannelConfig & UpdateChannelConfig>;

      setConfigActionKey('save');
      if (editingConfig) {
        const updatePayload = Object.fromEntries(
          Object.entries(payload).filter(([key]) => key !== 'channel_type')
        ) as UpdateChannelConfig;
        await channelService.updateConfig(editingConfig.id, updatePayload);
        message.success(t('tenant.pluginHub.configModal.updateSuccess'));
      } else {
        const channelType =
          typeof mutablePayload.channel_type === 'string' ? mutablePayload.channel_type : undefined;
        const channelName =
          typeof mutablePayload.name === 'string' ? mutablePayload.name : undefined;
        if (!channelType || !channelName) {
          message.error(t('tenant.pluginHub.configModal.channelTypeNameRequired'));
          return;
        }
        await channelService.createConfig(selectedProjectId, {
          ...payload,
          channel_type: channelType,
          name: channelName,
        });
        message.success(t('tenant.pluginHub.configModal.createSuccess'));
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
  }, [activeChannelSchema, editingConfig, form, loadChannelConfigs, selectedProjectId, t]);

  const dynamicSchemaFields = useMemo(() => {
    if (!activeChannelSchema?.schema_supported) return [];
    const properties = activeChannelSchema.config_schema?.properties || {};
    const required = new Set(activeChannelSchema.config_schema?.required || []);
    const hints = activeChannelSchema.config_ui_hints || {};
    const secretPaths = new Set(activeChannelSchema.secret_paths);

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
          ? [
              {
                required: true,
                message: t('tenant.pluginHub.configModal.pleaseEnter', { field: label }),
              },
            ]
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
            <Form.Item
              key={fieldName}
              name={formName}
              label={label}
              {...(rules != null ? { rules } : {})}
            >
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
            <Form.Item
              key={fieldName}
              name={formName}
              label={label}
              {...(rules != null ? { rules } : {})}
            >
              <InputNumber
                style={{ width: '100%' }}
                {...(schema.minimum != null ? { min: schema.minimum } : {})}
                {...(schema.maximum != null ? { max: schema.maximum } : {})}
                placeholder={placeholder}
              />
            </Form.Item>
          );
        }

        return (
          <Form.Item
            key={fieldName}
            name={formName}
            label={label}
            {...(rules != null ? { rules } : {})}
          >
            {sensitive ? (
              <Input.Password
                placeholder={
                  editingConfig
                    ? t('tenant.pluginHub.configModal.leaveUnchanged', {
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
      })
      .filter(Boolean);
  }, [activeChannelSchema, editingConfig, t]);

  const pluginColumns = [
    {
      title: t('tenant.pluginHub.pluginsList.plugin'),
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: RuntimePlugin) => (
        <Space orientation="vertical" size={0}>
          <Text strong>{name}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {record.package || t('tenant.pluginHub.pluginsList.local')}
            {record.version ? `@${record.version}` : ''}
          </Text>
        </Space>
      ),
    },
    {
      title: t('tenant.pluginHub.pluginsList.source'),
      dataIndex: 'source',
      key: 'source',
      render: (source: string) => <Tag>{source}</Tag>,
    },
    {
      title: t('tenant.pluginHub.channelsList.channels'),
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
          <Text type="secondary">{t('tenant.pluginHub.pluginsList.toolOnly')}</Text>
        ),
    },
    {
      title: t('tenant.pluginHub.channelsList.status'),
      key: 'status',
      render: (_: unknown, record: RuntimePlugin) =>
        record.enabled ? (
          <Badge status="success" text={t('tenant.pluginHub.pluginsList.enable')} />
        ) : (
          <Badge status="default" text={t('tenant.pluginHub.pluginsList.disabled')} />
        ),
    },
    {
      title: t('tenant.pluginHub.channelsList.actions'),
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
              {t('tenant.pluginHub.pluginsList.disable')}
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
              {t('tenant.pluginHub.pluginsList.enable')}
            </Button>
          )}
          <Popconfirm
            title={t('tenant.pluginHub.pluginsList.confirmUninstallNamed', { name: record.name })}
            description={t('tenant.pluginHub.pluginsList.uninstallDescription')}
            onConfirm={() => {
              void handleUninstallPlugin(record);
            }}
            okText={t('tenant.pluginHub.pluginsList.uninstall')}
            okButtonProps={{ danger: true }}
            disabled={!record.package}
          >
            <Button
              size="small"
              danger
              disabled={!record.package}
              loading={pluginActionKey === `${record.name}:uninstall`}
            >
              {t('tenant.pluginHub.pluginsList.uninstall')}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const configColumns = [
    {
      title: t('tenant.pluginHub.channelsList.name'),
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: ChannelConfig) => (
        <Space>
          <Text strong>{name}</Text>
          {record.enabled ? (
            <Tag color="success">{t('tenant.pluginHub.pluginsList.enable')}</Tag>
          ) : (
            <Tag>{t('tenant.pluginHub.pluginsList.disabled')}</Tag>
          )}
        </Space>
      ),
    },
    {
      title: t('tenant.pluginHub.channelsList.channelType'),
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
      title: t('tenant.pluginHub.channelsList.status'),
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        if (status === 'connected')
          return <Badge status="success" text={t('tenant.pluginHub.status.connected')} />;
        if (status === 'error')
          return <Badge status="error" text={t('tenant.pluginHub.status.error')} />;
        if (status === 'circuit_open')
          return <Badge color="orange" text={t('tenant.pluginHub.status.circuitOpen')} />;
        return <Badge status="default" text={t('tenant.pluginHub.status.disconnected')} />;
      },
    },
    {
      title: t('tenant.pluginHub.channelsList.actions'),
      key: 'actions',
      render: (_: unknown, record: ChannelConfig) => (
        <Space>
          <Button
            size="small"
            icon={<RefreshCw size={16} />}
            aria-label={t('tenant.pluginHub.channelsList.testChannel', { name: record.name })}
            title={t('tenant.pluginHub.channelsList.testChannel', { name: record.name })}
            loading={configActionKey === `test:${record.id}`}
            onClick={() => {
              void handleTestConfig(record.id);
            }}
          />
          <Button
            size="small"
            icon={<Pencil size={16} />}
            aria-label={t('tenant.pluginHub.channelsList.editChannel', { name: record.name })}
            title={t('tenant.pluginHub.channelsList.editChannel', { name: record.name })}
            onClick={() => {
              handleEditConfig(record);
            }}
          />
          <Popconfirm
            title={t('tenant.pluginHub.channelsList.deleteConfirm')}
            onConfirm={() => {
              void handleDeleteConfig(record.id);
            }}
            okText={t('tenant.pluginHub.channelsList.delete')}
            okButtonProps={{ danger: true }}
          >
            <Button
              size="small"
              danger
              icon={<Trash2 size={16} />}
              aria-label={t('tenant.pluginHub.channelsList.deleteChannel', { name: record.name })}
              title={t('tenant.pluginHub.channelsList.deleteChannel', { name: record.name })}
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
        <Empty description={t('tenant.pluginHub.missingTenantContext')} />
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
                {t('tenant.pluginHub.title')}
              </Title>
              <Text type="secondary">{t('tenant.pluginHub.subtitle')}</Text>
            </div>
          </div>

          <Space wrap>
            <Select
              style={{ minWidth: 240 }}
              placeholder={t('tenant.pluginHub.selectProjectPlaceholder')}
              value={selectedProjectId || undefined}
              options={projectOptions}
              onChange={(value) => {
                setSelectedProjectId(value ?? null);
              }}
              loading={projectLoading}
            />
            <Input
              placeholder={t('tenant.pluginHub.pluginsList.installPlaceholder')}
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
              {t('tenant.pluginHub.pluginsList.install')}
            </Button>
            <Button
              icon={<RefreshCw size={16} />}
              loading={pluginActionKey === 'reload'}
              onClick={() => {
                void handleReloadPlugins();
              }}
            >
              {t('tenant.pluginHub.pluginsList.reload')}
            </Button>
          </Space>
        </div>
      </section>

      <section className="bg-white dark:bg-surface-dark rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div className="px-5 pt-5 pb-2">
          <Title level={5} style={{ margin: 0 }}>
            {t('tenant.pluginHub.pluginsList.installedPlugins')}
          </Title>
        </div>
        <div className="px-5 pb-5">
          {lastPluginActionDetails?.control_plane_trace && (
            <div className="mb-4 rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-2">
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
                    {t('tenant.pluginHub.reloadPlanLabel')}:{' '}
                    {Object.entries(lastPluginActionDetails.channel_reload_plan)
                      .map(([key, value]) => `${key}=${value.toString()}`)
                      .join(', ')}
                  </Text>
                )}
              </Space>
            </div>
          )}
          {pluginActionTimeline.length > 0 && (
            <div className="mb-4 rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-2">
              <div className="text-xs font-medium text-slate-600 dark:text-slate-300">
                {t('tenant.pluginHub.operationTimeline')}
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
                        {t('tenant.pluginHub.reloadPlanLabel')}:{' '}
                        {Object.entries(entry.details.channel_reload_plan)
                          .map(([key, value]) => `${key}=${value.toString()}`)
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
            scroll={{ x: 'max-content' }}
            pagination={{ pageSize: 8 }}
          />
        </div>
      </section>

      <section className="bg-white dark:bg-surface-dark rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div className="px-5 pt-5 pb-2 flex items-center justify-between">
          <Title level={5} style={{ margin: 0 }}>
            {t('tenant.pluginHub.channelsList.configuredChannels')}
          </Title>
          <Button
            type="primary"
            icon={<Plus size={16} />}
            onClick={handleAddConfig}
            disabled={!selectedProjectId}
          >
            {t('tenant.pluginHub.channelsList.addChannel')}
          </Button>
        </div>
        <div className="px-5 pb-5">
          {selectedProjectId ? (
            <Table
              dataSource={channelConfigs}
              columns={configColumns}
              rowKey="id"
              loading={configsLoading}
              scroll={{ x: 'max-content' }}
              pagination={{ pageSize: 8 }}
            />
          ) : (
            <Empty description={t('tenant.pluginHub.channelsList.selectProjectToConfigure')} />
          )}
        </div>
      </section>

      <section className="bg-white dark:bg-surface-dark rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm p-5">
        <Title level={5} style={{ marginTop: 0 }}>
          {t('tenant.pluginHub.channelCatalogDiagnostics')}
        </Title>
        {channelPluginCatalog.length > 0 ? (
          <Space wrap>
            {channelPluginCatalog.map((entry) => (
              <Tag key={`${entry.plugin_name}:${entry.channel_type}`} color="processing">
                {humanizeChannelType(entry.channel_type)} · {entry.plugin_name}
                {entry.schema_supported ? ` · ${t('tenant.pluginHub.schemaSupported')}` : ''}
              </Tag>
            ))}
          </Space>
        ) : (
          <Text type="secondary">{t('tenant.pluginHub.noChannelAdapters')}</Text>
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
        title={
          editingConfig
            ? t('tenant.pluginHub.configModal.editTitle')
            : t('tenant.pluginHub.configModal.addTitle')
        }
        onCancel={() => {
          setConfigModalVisible(false);
          setEditingConfig(null);
          form.resetFields();
        }}
        onOk={() => {
          void handleSaveConfig();
        }}
        confirmLoading={configActionKey === 'save'}
        width={760}
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="channel_type"
            label={t('tenant.pluginHub.channelsList.channelType')}
            rules={[{ required: true }]}
          >
            <Select
              options={channelTypeOptions.map((option) => ({
                value: option.value,
                label: option.label,
              }))}
            />
          </Form.Item>

          <Form.Item
            name="name"
            label={t('tenant.pluginHub.channelsList.name')}
            rules={[{ required: true, message: t('tenant.pluginHub.configModal.pleaseEnterName') }]}
          >
            <Input placeholder={t('tenant.pluginHub.configModal.namePlaceholder')} />
          </Form.Item>

          <Form.Item
            name="enabled"
            label={t('tenant.pluginHub.pluginsList.enable')}
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>

          {activeChannelSchema?.schema_supported ? (
            <>
              {schemaLoading && (
                <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
                  {t('tenant.pluginHub.configModal.loadingSchema')}
                </Text>
              )}
              {dynamicSchemaFields}
            </>
          ) : (
            <>
              <Form.Item
                name="connection_mode"
                label={t('tenant.pluginHub.configModal.connectionMode')}
              >
                <Select
                  options={[
                    {
                      label: t('tenant.pluginHub.configModal.connectionModeWebsocket'),
                      value: 'websocket',
                    },
                    {
                      label: t('tenant.pluginHub.configModal.connectionModeWebhook'),
                      value: 'webhook',
                    },
                  ]}
                />
              </Form.Item>

              <Form.Item name="app_id" label={t('tenant.pluginHub.configModal.appId')}>
                <Input placeholder="cli_xxx" />
              </Form.Item>

              <Form.Item
                name="app_secret"
                label={
                  editingConfig
                    ? t('tenant.pluginHub.configModal.appSecretKeepUnchanged')
                    : t('tenant.pluginHub.configModal.appSecret')
                }
              >
                <Input.Password placeholder={t('tenant.pluginHub.configModal.enterAppSecret')} />
              </Form.Item>

              <Form.Item name="encrypt_key" label={t('tenant.pluginHub.configModal.encryptKey')}>
                <Input.Password
                  placeholder={t('tenant.pluginHub.configModal.encryptKeyPlaceholder')}
                />
              </Form.Item>

              <Form.Item
                name="verification_token"
                label={t('tenant.pluginHub.configModal.verificationToken')}
              >
                <Input.Password
                  placeholder={t('tenant.pluginHub.configModal.verificationTokenPlaceholder')}
                />
              </Form.Item>

              <Form.Item name="webhook_url" label={t('tenant.pluginHub.configModal.webhookUrl')}>
                <Input placeholder="https://your-domain.com/webhook" />
              </Form.Item>

              <Form.Item name="domain" label={t('tenant.pluginHub.configModal.domain')}>
                <Input placeholder={t('tenant.pluginHub.configModal.domainPlaceholder')} />
              </Form.Item>
            </>
          )}

          <Form.Item name="description" label={t('tenant.pluginHub.configModal.description')}>
            <Input.TextArea
              rows={2}
              placeholder={t('tenant.pluginHub.configModal.descriptionPlaceholder')}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default PluginHub;
