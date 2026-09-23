import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { App, Button, Empty, Form, Input, Modal, Select, Space, Switch, Typography } from 'antd';
import { Package, RefreshCw } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useUser } from '@/stores/auth';
import { useProjectStore } from '@/stores/project';
import { useTenantStore } from '@/stores/tenant';

import { channelService } from '@/services/channelService';
import { pluginMarketplaceService } from '@/services/pluginMarketplaceService';

import {
  CHANNEL_SETTING_FIELDS,
  SECRET_UNCHANGED_SENTINEL,
  getChannelConfigEditValues,
  getChannelConfigSubmitValues,
  isRecord,
} from '@/utils/channelConfigSanitizers';
import { buildMarketplaceInstallRequest } from '@/utils/pluginMarketplaceInstall';

import { SkeletonLoader } from '@/components/common/SkeletonLoader';
import { InstallPluginPackageModal } from '@/components/marketplace/InstallPluginPackageModal';
import { PluginMarketplaceV3 } from '@/components/marketplace/v3/PluginMarketplaceV3';

import { ChannelConfigSection } from './ChannelConfigSection';
import { PluginMarketplaceSection } from './PluginMarketplaceSection';
import { renderSchemaFormFields } from './pluginSchemaForm';

import type {
  ChannelConfig,
  ChannelPluginCatalogItem,
  ChannelPluginConfigSchema,
  CreateChannelConfig,
  UpdateChannelConfig,
} from '@/types/channel';
import type { Project } from '@/types/memory';
import type { MarketplacePackageCatalogEntry } from '@/types/pluginMarketplace';

const { Title, Text } = Typography;
const PROJECT_PICKER_PAGE_SIZE = 100;

const humanizeChannelType = (channelType: string): string =>
  channelType
    .split(/[-_]/g)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(' ');

export const PluginHub: React.FC = () => {
  const { tenantId: urlTenantId } = useParams<{ tenantId?: string | undefined }>();
  const { t } = useTranslation();
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const projectIdFromQuery = searchParams.get('projectId');
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const tenantId = urlTenantId || currentTenant?.id || null;
  const currentUser = useUser();
  const canInstallPackages = currentUser?.is_superuser === true;

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
  const watchedChannelType: unknown = Form.useWatch('channel_type', form);
  const selectedChannelType =
    typeof watchedChannelType === 'string' ? watchedChannelType : undefined;

  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [packages, setPackages] = useState<MarketplacePackageCatalogEntry[]>([]);
  const [channelPluginCatalog, setChannelPluginCatalog] = useState<ChannelPluginCatalogItem[]>([]);
  const [channelConfigs, setChannelConfigs] = useState<ChannelConfig[]>([]);
  const [channelSchemas, setChannelSchemas] = useState<Record<string, ChannelPluginConfigSchema>>(
    {}
  );
  const [marketplaceLoading, setMarketplaceLoading] = useState(false);
  const [marketplaceError, setMarketplaceError] = useState<string | null>(null);
  const [configsLoading, setConfigsLoading] = useState(false);
  const [schemaLoading, setSchemaLoading] = useState(false);
  const [packageActionKey, setPackageActionKey] = useState<string | null>(null);
  const [installTarget, setInstallTarget] = useState<MarketplacePackageCatalogEntry | null>(null);
  const [installError, setInstallError] = useState<string | null>(null);
  const [configActionKey, setConfigActionKey] = useState<string | null>(null);
  const [configModalVisible, setConfigModalVisible] = useState(false);
  const [editingConfig, setEditingConfig] = useState<ChannelConfig | null>(null);

  const activeTenantIdRef = useRef<string | null>(tenantId);
  const activeProjectIdRef = useRef<string | null>(selectedProjectId);
  const marketplaceRequestRef = useRef(0);
  const channelConfigsRequestRef = useRef(0);
  const channelSchemaRequestRef = useRef(0);

  activeTenantIdRef.current = tenantId;
  activeProjectIdRef.current = selectedProjectId;

  useEffect(() => {
    if (!tenantId) return;
    listProjects(tenantId, { page: 1, page_size: PROJECT_PICKER_PAGE_SIZE }).catch(() => {
      message.error(t('tenant.pluginHub.messages.loadProjectsFailed'));
    });
  }, [listProjects, message, tenantId, t]);

  useEffect(() => {
    marketplaceRequestRef.current += 1;
    channelConfigsRequestRef.current += 1;
    channelSchemaRequestRef.current += 1;
    setPackages([]);
    setChannelPluginCatalog([]);
    setChannelConfigs([]);
    setChannelSchemas({});
    setMarketplaceLoading(false);
    setMarketplaceError(null);
    setInstallTarget(null);
    setInstallError(null);
    setConfigsLoading(false);
    setSchemaLoading(false);
    setConfigModalVisible(false);
    setEditingConfig(null);
    form.resetFields();
  }, [form, tenantId]);

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
    setSelectedProjectId((current) => {
      if (current && tenantProjects.some((project) => project.id === current)) {
        return current;
      }
      return tenantProjects[0]?.id ?? null;
    });
  }, [projectIdFromQuery, tenantProjects]);

  const loadMarketplace = useCallback(async () => {
    const requestTenantId = tenantId;
    const requestId = ++marketplaceRequestRef.current;
    if (!requestTenantId || activeTenantIdRef.current !== requestTenantId) return;

    setMarketplaceLoading(true);
    try {
      const [nextPackages, catalog] = await Promise.all([
        pluginMarketplaceService.listPackages({ includeRevoked: true }),
        channelService.listTenantChannelPluginCatalog(requestTenantId),
      ]);
      if (
        marketplaceRequestRef.current !== requestId ||
        activeTenantIdRef.current !== requestTenantId
      ) {
        return;
      }
      setPackages(nextPackages);
      setChannelPluginCatalog(catalog.items);
      setMarketplaceError(null);
    } catch (loadError) {
      if (
        marketplaceRequestRef.current !== requestId ||
        activeTenantIdRef.current !== requestTenantId
      ) {
        return;
      }
      setMarketplaceError(
        loadError instanceof Error
          ? loadError.message
          : t('tenant.pluginHub.messages.loadPluginsFailed')
      );
    } finally {
      if (
        marketplaceRequestRef.current === requestId &&
        activeTenantIdRef.current === requestTenantId
      ) {
        setMarketplaceLoading(false);
      }
    }
  }, [tenantId, t]);

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
      if (
        channelConfigsRequestRef.current !== requestId ||
        activeProjectIdRef.current !== requestProjectId
      ) {
        return;
      }
      setChannelConfigs(items);
    } catch (loadError) {
      if (
        channelConfigsRequestRef.current !== requestId ||
        activeProjectIdRef.current !== requestProjectId
      ) {
        return;
      }
      message.error(
        loadError instanceof Error
          ? loadError.message
          : t('tenant.pluginHub.channelsList.loadFailed')
      );
    } finally {
      if (
        channelConfigsRequestRef.current === requestId &&
        activeProjectIdRef.current === requestProjectId
      ) {
        setConfigsLoading(false);
      }
    }
  }, [message, selectedProjectId, t]);

  const loadChannelSchema = useCallback(
    async (channelType: string) => {
      const requestTenantId = tenantId;
      const requestId = ++channelSchemaRequestRef.current;
      if (!requestTenantId || !channelType || channelSchemas[channelType]) return;
      const catalogEntry = channelPluginCatalog.find((item) => item.channel_type === channelType);
      if (!catalogEntry?.schema_supported) return;

      setSchemaLoading(true);
      try {
        const schema = await channelService.getTenantChannelPluginSchema(
          requestTenantId,
          channelType
        );
        if (
          channelSchemaRequestRef.current !== requestId ||
          activeTenantIdRef.current !== requestTenantId
        ) {
          return;
        }
        setChannelSchemas((current) => ({ ...current, [channelType]: schema }));
      } catch (loadError) {
        if (
          channelSchemaRequestRef.current !== requestId ||
          activeTenantIdRef.current !== requestTenantId
        ) {
          return;
        }
        message.error(
          loadError instanceof Error
            ? loadError.message
            : t('tenant.pluginHub.messages.loadSchemaFailed')
        );
      } finally {
        if (
          channelSchemaRequestRef.current === requestId &&
          activeTenantIdRef.current === requestTenantId
        ) {
          setSchemaLoading(false);
        }
      }
    },
    [channelPluginCatalog, channelSchemas, message, tenantId, t]
  );

  useEffect(() => {
    if (!tenantId) return;
    void loadMarketplace();
  }, [loadMarketplace, tenantId]);

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
    const currentValues = form.getFieldsValue(true) as Record<string, unknown>;
    const nextValues: Record<string, unknown> = {};
    const currentExtraSettings = isRecord(currentValues.extra_settings)
      ? { ...currentValues.extra_settings }
      : {};

    Object.entries(activeChannelSchema.defaults).forEach(([key, value]) => {
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
    () => tenantProjects.map((project) => ({ label: project.name, value: project.id })),
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
    return Array.from(optionMap.values());
  }, [channelConfigs, channelPluginCatalog]);

  const openPluginDetail = useCallback(
    (pluginId: string) => {
      if (!tenantId) return;
      void navigate(`/tenant/${tenantId}/plugins/${encodeURIComponent(pluginId)}`);
    },
    [navigate, tenantId]
  );

  const handleUninstallPackage = useCallback(
    async (entry: MarketplacePackageCatalogEntry) => {
      if (!tenantId) return;
      const actionKey = `${entry.plugin_id}:${entry.version}`;
      setPackageActionKey(actionKey);
      try {
        await pluginMarketplaceService.uninstallPackage(entry.plugin_id, {
          tenant_id: tenantId,
          version: entry.version,
        });
        message.success(
          t('tenant.pluginHub.messages.pluginUninstalled', {
            name: entry.plugin_id,
            version: entry.version,
          })
        );
        await Promise.all([loadMarketplace(), loadChannelConfigs()]);
      } catch (uninstallError) {
        message.error(
          uninstallError instanceof Error
            ? uninstallError.message
            : t('tenant.pluginHub.messages.pluginUninstallFailed')
        );
      } finally {
        setPackageActionKey((current) => (current === actionKey ? null : current));
      }
    },
    [loadChannelConfigs, loadMarketplace, message, tenantId, t]
  );

  const handleOpenInstall = useCallback((entry: MarketplacePackageCatalogEntry) => {
    setInstallError(null);
    setInstallTarget(entry);
  }, []);

  const handleInstallPackage = useCallback(async () => {
    if (!tenantId || !installTarget) return;
    const request = buildMarketplaceInstallRequest(installTarget, tenantId);
    if (!request) {
      setInstallError(t('tenant.pluginHub.pluginsList.installUnavailable.unsigned'));
      return;
    }
    const actionKey = `install:${installTarget.plugin_id}:${installTarget.version}`;
    setPackageActionKey(actionKey);
    setInstallError(null);
    try {
      const outcome = await pluginMarketplaceService.installPackage(
        installTarget.plugin_id,
        request
      );
      if (outcome.status !== 'approved') {
        setInstallError(outcome.reason || t('tenant.pluginHub.messages.pluginInstallFailed'));
        return;
      }
      message.success(
        t('tenant.pluginHub.messages.pluginInstalled', {
          name: outcome.plugin_id,
          version: outcome.version,
        })
      );
      setInstallTarget(null);
      await Promise.all([loadMarketplace(), loadChannelConfigs()]);
    } catch (installError) {
      setInstallError(
        installError instanceof Error
          ? installError.message
          : t('tenant.pluginHub.messages.pluginInstallFailed')
      );
    } finally {
      setPackageActionKey((current) => (current === actionKey ? null : current));
    }
  }, [installTarget, loadChannelConfigs, loadMarketplace, message, tenantId, t]);

  const handleAddConfig = useCallback(() => {
    if (!selectedProjectId) {
      message.warning(t('tenant.pluginHub.messages.selectProjectFirst'));
      return;
    }
    const defaultChannelType = channelTypeOptions[0]?.value;
    if (!defaultChannelType) {
      message.warning(t('tenant.pluginHub.noChannelAdapters'));
      return;
    }
    setEditingConfig(null);
    form.resetFields();
    form.setFieldsValue({ channel_type: defaultChannelType, enabled: true });
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
      } catch (deleteError) {
        message.error(
          deleteError instanceof Error
            ? deleteError.message
            : t('tenant.pluginHub.channelsList.deleteFailed')
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
      } catch (testError) {
        message.error(
          testError instanceof Error
            ? testError.message
            : t('tenant.pluginHub.channelsList.testFailed')
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
    } catch (saveError) {
      if (saveError instanceof Error) {
        message.error(saveError.message);
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

  if (!tenantId) {
    return (
      <div className="flex h-full w-full max-w-full items-center justify-center">
        <Empty description={t('tenant.pluginHub.missingTenantContext')} />
      </div>
    );
  }

  return (
    <div className="mx-auto h-full w-full max-w-full space-y-4 p-4 md:p-6">
      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-surface-dark">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10">
              <Package size={20} className="text-primary" />
            </div>
            <div>
              <Title level={4} className="!m-0">
                {t('tenant.pluginHub.title')}
              </Title>
              <Text type="secondary">{t('tenant.pluginHub.subtitle')}</Text>
            </div>
          </div>
          <Space wrap>
            <Select
              aria-label={t('tenant.pluginHub.projectSelectorLabel')}
              className="min-w-[240px]"
              placeholder={t('tenant.pluginHub.selectProjectPlaceholder')}
              value={selectedProjectId || undefined}
              options={projectOptions}
              onChange={(value) => {
                setSelectedProjectId(value ?? null);
              }}
              loading={projectLoading}
            />
            <Button
              icon={<RefreshCw size={16} />}
              loading={marketplaceLoading || configsLoading}
              onClick={() => {
                void Promise.all([loadMarketplace(), loadChannelConfigs()]);
              }}
            >
              {t('tenant.pluginHub.pluginsList.reload')}
            </Button>
          </Space>
        </div>
      </section>

      {tenantId ? (
        <PluginMarketplaceV3
          tenantId={tenantId}
          projectId={selectedProjectId}
          onInstallSignedV2={
            canInstallPackages
              ? () => {
                  const installer = document.getElementById('signed-plugin-marketplace');
                  installer?.scrollIntoView({ block: 'start' });
                  installer?.focus({ preventScroll: true });
                }
              : undefined
          }
          canManage={
            canInstallPackages ||
            (Boolean(currentUser) && currentTenant?.owner_id === currentUser?.id) ||
            currentUser?.roles.some((role) => role === 'admin' || role === 'owner') === true
          }
        />
      ) : null}

      <div id="signed-plugin-marketplace" tabIndex={-1}>
        <PluginMarketplaceSection
          packages={packages}
          loading={marketplaceLoading}
          error={marketplaceError}
          actionKey={packageActionKey}
          canInstall={canInstallPackages}
          onRetry={() => {
            void loadMarketplace();
          }}
          onOpen={openPluginDetail}
          onInstall={handleOpenInstall}
          onUninstall={handleUninstallPackage}
        />
      </div>

      <InstallPluginPackageModal
        key={
          installTarget ? `${installTarget.plugin_id}:${installTarget.version}` : 'install-closed'
        }
        entry={installTarget}
        busy={
          installTarget !== null &&
          packageActionKey === `install:${installTarget.plugin_id}:${installTarget.version}`
        }
        error={installError}
        onCancel={() => {
          if (packageActionKey?.startsWith('install:')) return;
          setInstallTarget(null);
          setInstallError(null);
        }}
        onConfirm={() => {
          void handleInstallPackage();
        }}
      />

      <ChannelConfigSection
        selectedProjectId={selectedProjectId}
        configs={channelConfigs}
        catalog={channelPluginCatalog}
        channelTypeOptions={channelTypeOptions}
        loading={configsLoading}
        actionKey={configActionKey}
        onAdd={handleAddConfig}
        onEdit={handleEditConfig}
        onTest={handleTestConfig}
        onDelete={handleDeleteConfig}
      />

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

          {schemaLoading ? <SkeletonLoader type="form" /> : null}
          {!schemaLoading && activeChannelSchema?.schema_supported ? dynamicSchemaFields : null}
          {!schemaLoading && selectedChannelType && !activeChannelSchema?.schema_supported ? (
            <Empty description={t('tenant.pluginHub.pluginDetail.notSupported')} />
          ) : null}

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
