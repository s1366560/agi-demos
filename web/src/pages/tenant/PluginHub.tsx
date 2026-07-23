import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import {
  Alert,
  App,
  Badge,
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd';
import { Eye, Package, Trash2, Pencil, Plus, RefreshCw, Settings } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useProjectStore } from '@/stores/project';
import { useTenantStore } from '@/stores/tenant';

import { channelService } from '@/services/channelService';

import {
  CHANNEL_SETTING_FIELDS,
  SECRET_UNCHANGED_SENTINEL,
  getChannelConfigEditValues,
  getChannelConfigSubmitValues,
  isRecord,
} from '@/utils/channelConfigSanitizers';
import { formatDateTime } from '@/utils/date';
import { formatPluginCapabilityCounts } from '@/utils/pluginCapabilityCounts';

import { SkeletonLoader } from '@/components/common/SkeletonLoader';

import { renderSchemaFormFields, sanitizePluginConfigValues } from './pluginSchemaForm';

import type {
  ChannelConfig,
  ChannelPluginCatalogItem,
  ChannelPluginConfigSchema,
  CreateChannelConfig,
  PluginActionDetails,
  PluginActionResponse,
  PluginConfigSchema,
  PluginDiagnostic,
  RuntimePlugin,
  UpdateChannelConfig,
} from '@/types/channel';
import type { Project } from '@/types/memory';

const { Title, Text } = Typography;

const humanizeChannelType = (channelType: string): string =>
  channelType
    .split(/[-_]/g)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(' ');

const contractCount = (plugin: RuntimePlugin, key: string): number =>
  plugin.contracts?.[key]?.length ?? 0;

interface PluginActionTimelineEntry {
  id: string;
  action: string;
  message: string;
  success: boolean;
  timestamp: string;
  details: PluginActionDetails | null;
}

const PROJECT_PICKER_PAGE_SIZE = 100;

export const PluginHub: React.FC = () => {
  const { tenantId: urlTenantId } = useParams<{ tenantId?: string | undefined }>();
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
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
  const tenantProjects = useMemo(
    () => (tenantId ? projects.filter((project: Project) => project.tenant_id === tenantId) : []),
    [projects, tenantId]
  );

  const [form] = Form.useForm<Record<string, unknown>>();
  const [pluginConfigForm] = Form.useForm<Record<string, unknown>>();
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
  const [pluginConfigSchemas, setPluginConfigSchemas] = useState<
    Record<string, PluginConfigSchema>
  >({});

  const [pluginsLoading, setPluginsLoading] = useState(false);
  const [pluginsError, setPluginsError] = useState<string | null>(null);
  const [configsLoading, setConfigsLoading] = useState(false);
  const [schemaLoading, setSchemaLoading] = useState(false);
  const [pluginConfigLoading, setPluginConfigLoading] = useState(false);

  const [pluginActionKey, setPluginActionKey] = useState<string | null>(null);
  const [configActionKey, setConfigActionKey] = useState<string | null>(null);
  const [installRequirement, setInstallRequirement] = useState('');
  const [lastPluginActionDetails, setLastPluginActionDetails] =
    useState<PluginActionDetails | null>(null);
  const [pluginActionTimeline, setPluginActionTimeline] = useState<PluginActionTimelineEntry[]>([]);
  const [configModalVisible, setConfigModalVisible] = useState(false);
  const [editingConfig, setEditingConfig] = useState<ChannelConfig | null>(null);
  const [pluginConfigModalVisible, setPluginConfigModalVisible] = useState(false);
  const [configuringPlugin, setConfiguringPlugin] = useState<RuntimePlugin | null>(null);

  const activeTenantIdRef = useRef<string | null>(tenantId);
  const activeProjectIdRef = useRef<string | null>(selectedProjectId);
  const pluginRuntimeRequestRef = useRef(0);
  const channelConfigsRequestRef = useRef(0);
  const channelSchemaRequestRef = useRef(0);
  const pluginConfigRequestRef = useRef(0);

  activeTenantIdRef.current = tenantId;
  activeProjectIdRef.current = selectedProjectId;

  const isPluginRuntimeRequestCurrent = useCallback(
    (requestId: number, requestTenantId: string) =>
      pluginRuntimeRequestRef.current === requestId &&
      activeTenantIdRef.current === requestTenantId,
    []
  );

  const isChannelConfigsRequestCurrent = useCallback(
    (requestId: number, requestProjectId: string) =>
      channelConfigsRequestRef.current === requestId &&
      activeProjectIdRef.current === requestProjectId,
    []
  );

  const isChannelSchemaRequestCurrent = useCallback(
    (requestId: number, requestTenantId: string) =>
      channelSchemaRequestRef.current === requestId &&
      activeTenantIdRef.current === requestTenantId,
    []
  );

  const isPluginConfigRequestCurrent = useCallback(
    (requestId: number, requestTenantId: string) =>
      pluginConfigRequestRef.current === requestId && activeTenantIdRef.current === requestTenantId,
    []
  );

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
    listProjects(tenantId, { page: 1, page_size: PROJECT_PICKER_PAGE_SIZE }).catch(() => {
      message.error(t('tenant.pluginHub.messages.loadProjectsFailed'));
    });
  }, [listProjects, message, tenantId, t]);

  useEffect(() => {
    pluginRuntimeRequestRef.current += 1;
    channelConfigsRequestRef.current += 1;
    channelSchemaRequestRef.current += 1;
    pluginConfigRequestRef.current += 1;

    setPlugins([]);
    setPluginDiagnostics([]);
    setChannelPluginCatalog([]);
    setChannelConfigs([]);
    setChannelSchemas({});
    setPluginConfigSchemas({});
    setLastPluginActionDetails(null);
    setPluginActionTimeline([]);
    setPluginsLoading(false);
    setPluginsError(null);
    setConfigsLoading(false);
    setSchemaLoading(false);
    setPluginConfigLoading(false);
    setPluginConfigModalVisible(false);
    setConfiguringPlugin(null);
    pluginConfigForm.resetFields();
  }, [pluginConfigForm, tenantId]);

  useEffect(() => {
    channelConfigsRequestRef.current += 1;
    setChannelConfigs([]);
    setConfigsLoading(false);
  }, [selectedProjectId]);

  useEffect(() => {
    if (tenantProjects.length === 0) {
      setSelectedProjectId(null);
      return;
    }

    if (projectIdFromQuery && tenantProjects.some((project) => project.id === projectIdFromQuery)) {
      setSelectedProjectId(projectIdFromQuery);
      return;
    }

    setSelectedProjectId((prev) => {
      if (prev && tenantProjects.some((project) => project.id === prev)) {
        return prev;
      }
      return tenantProjects[0]?.id ?? null;
    });
  }, [projectIdFromQuery, tenantProjects]);

  const loadPluginRuntime = useCallback(async () => {
    const requestTenantId = tenantId;
    const requestId = ++pluginRuntimeRequestRef.current;
    if (!requestTenantId || activeTenantIdRef.current !== requestTenantId) return;

    setPluginsLoading(true);
    try {
      const [pluginRes, catalogRes] = await Promise.all([
        channelService.listTenantPlugins(requestTenantId),
        channelService.listTenantChannelPluginCatalog(requestTenantId),
      ]);
      if (!isPluginRuntimeRequestCurrent(requestId, requestTenantId)) return;
      setPlugins(pluginRes.items);
      setPluginDiagnostics(pluginRes.diagnostics);
      setChannelPluginCatalog(catalogRes.items);
      setPluginsError(null);
    } catch (error) {
      if (!isPluginRuntimeRequestCurrent(requestId, requestTenantId)) return;
      setPluginsError(
        error instanceof Error ? error.message : t('tenant.pluginHub.messages.loadPluginsFailed')
      );
    } finally {
      if (isPluginRuntimeRequestCurrent(requestId, requestTenantId)) {
        setPluginsLoading(false);
      }
    }
  }, [isPluginRuntimeRequestCurrent, tenantId, t]);

  const loadChannelConfigs = useCallback(async () => {
    const requestProjectId = selectedProjectId;
    const requestId = ++channelConfigsRequestRef.current;
    if (!requestProjectId) {
      setChannelConfigs([]);
      return;
    }
    if (activeProjectIdRef.current !== requestProjectId) return;

    setConfigsLoading(true);
    try {
      const items = await channelService.listConfigs(requestProjectId);
      if (!isChannelConfigsRequestCurrent(requestId, requestProjectId)) return;
      setChannelConfigs(items);
    } catch (error) {
      if (!isChannelConfigsRequestCurrent(requestId, requestProjectId)) return;
      message.error(
        error instanceof Error ? error.message : t('tenant.pluginHub.channelsList.loadFailed')
      );
    } finally {
      if (isChannelConfigsRequestCurrent(requestId, requestProjectId)) {
        setConfigsLoading(false);
      }
    }
  }, [isChannelConfigsRequestCurrent, message, selectedProjectId, t]);

  const loadChannelSchema = useCallback(
    async (channelType: string) => {
      const requestTenantId = tenantId;
      const requestId = ++channelSchemaRequestRef.current;
      if (!requestTenantId || !channelType) return;
      if (activeTenantIdRef.current !== requestTenantId) return;
      if (channelSchemas[channelType]) return;
      const catalogEntry = channelPluginCatalog.find((item) => item.channel_type === channelType);
      if (!catalogEntry?.schema_supported) return;

      setSchemaLoading(true);
      try {
        const schema = await channelService.getTenantChannelPluginSchema(
          requestTenantId,
          channelType
        );
        if (!isChannelSchemaRequestCurrent(requestId, requestTenantId)) return;
        setChannelSchemas((prev) => ({ ...prev, [channelType]: schema }));
      } catch (error) {
        if (!isChannelSchemaRequestCurrent(requestId, requestTenantId)) return;
        message.error(
          error instanceof Error ? error.message : t('tenant.pluginHub.messages.loadSchemaFailed')
        );
      } finally {
        if (isChannelSchemaRequestCurrent(requestId, requestTenantId)) {
          setSchemaLoading(false);
        }
      }
    },
    [channelPluginCatalog, channelSchemas, isChannelSchemaRequestCurrent, message, tenantId, t]
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
  const activePluginConfigSchema = configuringPlugin
    ? pluginConfigSchemas[configuringPlugin.name]
    : undefined;

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
      tenantProjects.map((project: Project) => ({
        label: project.name,
        value: project.id,
      })),
    [tenantProjects]
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
  }, [
    installRequirement,
    loadChannelConfigs,
    loadPluginRuntime,
    message,
    recordPluginAction,
    tenantId,
    t,
  ]);

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
    [loadChannelConfigs, loadPluginRuntime, message, recordPluginAction, tenantId, t]
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
  }, [loadChannelConfigs, loadPluginRuntime, message, recordPluginAction, tenantId, t]);

  const openPluginDetail = useCallback(
    (pluginName: string) => {
      if (!tenantId) return;
      const projectId = selectedProjectId || projectIdFromQuery;
      const query = projectId ? `?projectId=${encodeURIComponent(projectId)}` : '';
      void navigate(`/tenant/${tenantId}/plugins/${encodeURIComponent(pluginName)}${query}`);
    },
    [navigate, projectIdFromQuery, selectedProjectId, tenantId]
  );

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
    [loadChannelConfigs, loadPluginRuntime, message, recordPluginAction, tenantId, t]
  );

  const handleConfigurePlugin = useCallback(
    async (plugin: RuntimePlugin) => {
      const requestTenantId = tenantId;
      const requestId = ++pluginConfigRequestRef.current;
      if (!requestTenantId || !plugin.schema_supported) return;
      if (activeTenantIdRef.current !== requestTenantId) return;

      setConfiguringPlugin(plugin);
      setPluginConfigModalVisible(true);
      setPluginConfigLoading(true);
      pluginConfigForm.resetFields();
      try {
        const [schema, configRecord] = await Promise.all([
          channelService.getTenantPluginConfigSchema(requestTenantId, plugin.name),
          channelService.getTenantPluginConfig(requestTenantId, plugin.name),
        ]);
        if (!isPluginConfigRequestCurrent(requestId, requestTenantId)) return;
        setPluginConfigSchemas((prev) => ({ ...prev, [plugin.name]: schema }));
        pluginConfigForm.setFieldsValue({
          config: {
            ...(schema.defaults || {}),
            ...configRecord.config,
          },
        });
      } catch (error) {
        if (!isPluginConfigRequestCurrent(requestId, requestTenantId)) return;
        message.error(
          error instanceof Error ? error.message : t('tenant.pluginHub.messages.loadSchemaFailed')
        );
        setPluginConfigModalVisible(false);
        setConfiguringPlugin(null);
      } finally {
        if (isPluginConfigRequestCurrent(requestId, requestTenantId)) {
          setPluginConfigLoading(false);
        }
      }
    },
    [isPluginConfigRequestCurrent, message, pluginConfigForm, tenantId, t]
  );

  const handleSavePluginConfig = useCallback(async () => {
    if (!tenantId || !configuringPlugin || !activePluginConfigSchema?.schema_supported) return;
    const actionKey = `${configuringPlugin.name}:config`;
    try {
      const values = await pluginConfigForm.validateFields();
      const rawConfig = isRecord(values.config) ? values.config : {};
      const secretPaths = new Set(activePluginConfigSchema.secret_paths);
      const allowedFields = new Set(
        Object.keys(activePluginConfigSchema.config_schema?.properties || {})
      );
      const config = sanitizePluginConfigValues(rawConfig, secretPaths, allowedFields);
      setPluginActionKey(actionKey);
      await channelService.updateTenantPluginConfig(tenantId, configuringPlugin.name, { config });
      message.success(t('tenant.pluginHub.configModal.updateSuccess'));
      setPluginConfigModalVisible(false);
      setConfiguringPlugin(null);
      pluginConfigForm.resetFields();
      await loadPluginRuntime();
    } catch (error) {
      if (error instanceof Error) {
        message.error(error.message);
      }
    } finally {
      setPluginActionKey((current) => (current === actionKey ? null : current));
    }
  }, [
    activePluginConfigSchema,
    configuringPlugin,
    loadPluginRuntime,
    message,
    pluginConfigForm,
    tenantId,
    t,
  ]);

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
  }, [channelTypeOptions, form, loadChannelSchema, message, selectedProjectId, t]);

  const handleEditConfig = useCallback(
    (config: ChannelConfig) => {
      setEditingConfig(config);
      form.resetFields();
      form.setFieldsValue(
        getChannelConfigEditValues(config) as Parameters<typeof form.setFieldsValue>[0]
      );
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
    [loadChannelConfigs, message, t]
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
    [loadChannelConfigs, message, t]
  );

  const handleSaveConfig = useCallback(async () => {
    if (!selectedProjectId) {
      message.warning(t('tenant.pluginHub.messages.selectProjectFirst'));
      return;
    }
    try {
      const values = await form.validateFields();
      const payload = getChannelConfigSubmitValues(
        values as CreateChannelConfig | UpdateChannelConfig,
        {
          editingConfig,
          schemaSecretPaths: activeChannelSchema?.secret_paths,
          schemaSupported: activeChannelSchema?.schema_supported,
        }
      );

      setConfigActionKey('save');
      if (editingConfig) {
        const updatePayload = Object.fromEntries(
          Object.entries(payload).filter(([key]) => key !== 'channel_type')
        ) as UpdateChannelConfig;
        await channelService.updateConfig(editingConfig.id, updatePayload);
        message.success(t('tenant.pluginHub.configModal.updateSuccess'));
      } else {
        const channelType =
          typeof payload.channel_type === 'string' ? payload.channel_type : undefined;
        const channelName = typeof payload.name === 'string' ? payload.name : undefined;
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
  }, [activeChannelSchema, editingConfig, form, loadChannelConfigs, message, selectedProjectId, t]);

  const dynamicSchemaFields = useMemo(
    () =>
      renderSchemaFormFields({
        schemaSupported: activeChannelSchema?.schema_supported ?? false,
        properties: activeChannelSchema?.config_schema?.properties ?? {},
        requiredFields: activeChannelSchema?.config_schema?.required ?? [],
        uiHints: activeChannelSchema?.config_ui_hints ?? {},
        secretPaths: activeChannelSchema?.secret_paths ?? [],
        excludeFields: ['channel_type', 'name', 'enabled'],
        resolveFormName: (fieldName) =>
          CHANNEL_SETTING_FIELDS.has(fieldName) ? fieldName : ['extra_settings', fieldName],
        isRequiredField: (sensitive) => !(editingConfig && sensitive),
        resolveSecretPlaceholder: (placeholder) =>
          editingConfig
            ? t('tenant.pluginHub.configModal.leaveUnchanged', {
                sentinel: SECRET_UNCHANGED_SENTINEL,
              })
            : placeholder,
        t,
      }),
    [activeChannelSchema, editingConfig, t]
  );

  const pluginConfigDynamicFields = useMemo(
    () =>
      renderSchemaFormFields({
        schemaSupported: activePluginConfigSchema?.schema_supported ?? false,
        properties: activePluginConfigSchema?.config_schema?.properties ?? {},
        requiredFields: activePluginConfigSchema?.config_schema?.required ?? [],
        uiHints: activePluginConfigSchema?.config_ui_hints ?? {},
        secretPaths: activePluginConfigSchema?.secret_paths ?? [],
        resolveFormName: (fieldName) => ['config', fieldName],
        isRequiredField: (sensitive) => !sensitive,
        resolveSecretPlaceholder: () =>
          t('tenant.pluginHub.configModal.leaveUnchanged', {
            sentinel: SECRET_UNCHANGED_SENTINEL,
          }),
        t,
      }),
    [activePluginConfigSchema, t]
  );

  const renderPaginationItem = useCallback(
    (_page: number, type: string, originalElement: React.ReactNode) => {
      const label =
        type === 'prev'
          ? t('tenant.pluginHub.pagination.previousPage')
          : type === 'next'
            ? t('tenant.pluginHub.pagination.nextPage')
            : undefined;

      if (!label || !React.isValidElement(originalElement)) {
        return originalElement;
      }

      return React.cloneElement(originalElement, {
        'aria-label': label,
        title: label,
      } as React.AriaAttributes & { title: string });
    },
    [t]
  );

  const pluginPagination = useMemo(
    () =>
      plugins.length > 8
        ? {
            pageSize: 8,
            showSizeChanger: false,
            itemRender: renderPaginationItem,
          }
        : false,
    [plugins.length, renderPaginationItem]
  );

  const channelPagination = useMemo(
    () =>
      channelConfigs.length > 8
        ? {
            pageSize: 8,
            showSizeChanger: false,
            itemRender: renderPaginationItem,
          }
        : false,
    [channelConfigs.length, renderPaginationItem]
  );

  const pluginColumns = [
    {
      title: t('tenant.pluginHub.pluginsList.plugin'),
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: RuntimePlugin) => (
        <Space orientation="vertical" size={0}>
          <Button
            type="link"
            className="h-auto p-0 text-left font-medium"
            onClick={() => {
              openPluginDetail(record.name);
            }}
          >
            {name}
          </Button>
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
      title: t('tenant.pluginHub.pluginsList.capabilities'),
      key: 'capabilities',
      render: (_: unknown, record: RuntimePlugin) => {
        const capabilities = [
          {
            key: 'tools',
            count: contractCount(record, 'tools'),
            label: t('tenant.pluginHub.pluginsList.capabilityTools'),
          },
          {
            key: 'skills',
            count: contractCount(record, 'skills'),
            label: t('tenant.pluginHub.pluginsList.capabilitySkills'),
          },
          {
            key: 'commands',
            count: Math.max(contractCount(record, 'commands'), record.command_aliases?.length ?? 0),
            label: t('tenant.pluginHub.pluginsList.capabilityCommands'),
          },
          {
            key: 'hooks',
            count: contractCount(record, 'hooks'),
            label: t('tenant.pluginHub.pluginsList.capabilityHooks'),
          },
        ].filter((item) => item.count > 0);

        if (capabilities.length === 0) {
          return <Text type="secondary">{t('tenant.pluginHub.pluginsList.noCapabilities')}</Text>;
        }

        return (
          <Space wrap size={[4, 4]}>
            {capabilities.map((item) => (
              <Tag key={item.key}>
                {item.label}: {item.count}
              </Tag>
            ))}
          </Space>
        );
      },
    },
    {
      title: t('tenant.pluginHub.channelsList.status'),
      key: 'status',
      render: (_: unknown, record: RuntimePlugin) =>
        record.enabled ? (
          <Badge status="success" text={t('common.status.enabled')} />
        ) : (
          <Badge status="default" text={t('tenant.pluginHub.pluginsList.disabled')} />
        ),
    },
    {
      title: t('tenant.pluginHub.channelsList.actions'),
      key: 'actions',
      render: (_: unknown, record: RuntimePlugin) => (
        <Space>
          <Button
            size="small"
            icon={<Eye size={16} />}
            aria-label={t('tenant.pluginHub.pluginsList.viewPlugin', { name: record.name })}
            title={t('tenant.pluginHub.pluginsList.viewPlugin', { name: record.name })}
            onClick={() => {
              openPluginDetail(record.name);
            }}
          />
          <Button
            size="small"
            icon={<Settings size={16} />}
            aria-label={t('tenant.pluginHub.pluginsList.configurePlugin', { name: record.name })}
            title={t('tenant.pluginHub.pluginsList.configurePlugin', { name: record.name })}
            disabled={!record.schema_supported}
            loading={pluginConfigLoading && configuringPlugin?.name === record.name}
            onClick={() => {
              void handleConfigurePlugin(record);
            }}
          />
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
            <Tag color="success">{t('common.status.enabled')}</Tag>
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
              aria-label={t('tenant.pluginHub.projectSelectorLabel')}
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
              aria-label={t('tenant.pluginHub.pluginsList.installPlaceholder')}
              placeholder={t('tenant.pluginHub.pluginsList.installPlaceholder')}
              value={installRequirement}
              onChange={(event) => {
                setInstallRequirement(event.target.value);
              }}
              onPressEnter={() => {
                void handleInstallPlugin();
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
                      <Text type="secondary">{formatDateTime(entry.timestamp)}</Text>
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
          {pluginsError ? (
            <Alert
              type="error"
              showIcon
              className="mb-4"
              title={t('tenant.pluginHub.messages.loadPluginsFailed')}
              description={pluginsError}
              action={
                <Button
                  onClick={() => {
                    void loadPluginRuntime();
                  }}
                >
                  {t('common.retry')}
                </Button>
              }
            />
          ) : null}
          <Table
            dataSource={plugins}
            columns={pluginColumns}
            rowKey="name"
            loading={pluginsLoading}
            scroll={{ x: 'max-content' }}
            pagination={pluginPagination}
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
              pagination={channelPagination}
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
        open={pluginConfigModalVisible}
        title={t('tenant.pluginHub.pluginConfigModal.title', {
          name: configuringPlugin?.name || '',
        })}
        onCancel={() => {
          pluginConfigRequestRef.current += 1;
          setPluginConfigModalVisible(false);
          setConfiguringPlugin(null);
          setPluginConfigLoading(false);
          pluginConfigForm.resetFields();
        }}
        onOk={() => {
          void handleSavePluginConfig();
        }}
        confirmLoading={
          configuringPlugin ? pluginActionKey === `${configuringPlugin.name}:config` : false
        }
        width={720}
        destroyOnHidden
      >
        <Form form={pluginConfigForm} layout="vertical">
          {pluginConfigLoading ? (
            <SkeletonLoader type="form" />
          ) : activePluginConfigSchema?.schema_supported ? (
            pluginConfigDynamicFields
          ) : (
            <Empty description={t('tenant.pluginHub.pluginConfigModal.noConfig')} />
          )}
        </Form>
      </Modal>

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
              aria-label={t('tenant.pluginHub.channelsList.selectChannelType')}
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
              {schemaLoading && <SkeletonLoader type="form" />}
              {dynamicSchemaFields}
            </>
          ) : (
            <>
              <Form.Item
                name="connection_mode"
                label={t('tenant.pluginHub.configModal.connectionMode')}
              >
                <Select
                  aria-label={t('tenant.pluginHub.configModal.connectionMode')}
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
                <Input placeholder={t('tenant.pluginHub.configModal.appIdPlaceholder')} />
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
                <Input placeholder={t('tenant.pluginHub.configModal.webhookUrlPlaceholder')} />
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
