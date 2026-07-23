import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { Input, Tag, InputNumber, Table, Space } from 'antd';
import {
  AlertCircle,
  Link,
  Network,
  Plus,
  Unlink,
  Webhook,
  Plug,
  MessageCircle,
  MessageSquare,
  Mail,
  RefreshCw,
  Search as SearchIcon,
} from 'lucide-react';

import { instanceChannelService } from '@/services/instanceChannelService';

import { SkeletonLoader } from '@/components/common/SkeletonLoader';
import {
  useLazyMessage,
  LazyAlert,
  LazyButton,
  LazySelect,
  LazyPopconfirm,
  LazyEmpty,
  LazyModal,
} from '@/components/ui/lazyAntd';

import { formatDate } from './utils/instanceUtils';

import type { ColumnsType } from 'antd/es/table';

const { Search } = Input;

// Types for channel configuration
interface ChannelConfig {
  id: string;
  instance_id: string;
  channel_type: ChannelType;
  name: string;
  config: Record<string, unknown>;
  status: ChannelStatus;
  last_connected_at: string | null;
  created_at: string;
  updated_at: string | null;
}

type ChannelType = 'mcp' | 'webhook' | 'websocket' | 'api' | 'slack' | 'discord' | 'email';
type ChannelStatus = 'connected' | 'disconnected' | 'error' | 'pending';

interface ChannelTypeOption {
  value: ChannelType;
  labelKey: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  // Types without a config form (renderConfigFields default branch) are not
  // creatable yet — offering them would save a zero-config channel.
  implemented: boolean;
}

const DEFAULT_CHANNEL_TYPE_OPTION: ChannelTypeOption = {
  value: 'mcp',
  labelKey: 'tenant.instances.channels.types.mcp',
  icon: Network,
  implemented: true,
};

const CHANNEL_TYPE_OPTIONS: ChannelTypeOption[] = [
  DEFAULT_CHANNEL_TYPE_OPTION,
  {
    value: 'webhook',
    labelKey: 'tenant.instances.channels.types.webhook',
    icon: Webhook,
    implemented: true,
  },
  {
    value: 'websocket',
    labelKey: 'tenant.instances.channels.types.websocket',
    icon: Link,
    implemented: false,
  },
  { value: 'api', labelKey: 'tenant.instances.channels.types.api', icon: Plug, implemented: true },
  {
    value: 'slack',
    labelKey: 'tenant.instances.channels.types.slack',
    icon: MessageCircle,
    implemented: false,
  },
  {
    value: 'discord',
    labelKey: 'tenant.instances.channels.types.discord',
    icon: MessageSquare,
    implemented: false,
  },
  {
    value: 'email',
    labelKey: 'tenant.instances.channels.types.email',
    icon: Mail,
    implemented: false,
  },
];

const STATUS_COLORS: Record<ChannelStatus, string> = {
  connected: 'green',
  disconnected: 'default',
  error: 'red',
  pending: 'blue',
};

export const InstanceChannels: React.FC = () => {
  const { t } = useTranslation();
  const { instanceId } = useParams<{ instanceId: string }>();
  const messageApi = useLazyMessage();

  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [channels, setChannels] = useState<ChannelConfig[]>([]);
  const [search, setSearch] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingChannel, setEditingChannel] = useState<ChannelConfig | null>(null);
  const [testingChannelId, setTestingChannelId] = useState<string | null>(null);

  // Form state for add/edit
  const [formChannelType, setFormChannelType] = useState<ChannelType>('mcp');
  const [formName, setFormName] = useState('');
  const [formConfig, setFormConfig] = useState<Record<string, unknown>>({});

  const fetchChannels = useCallback(async () => {
    if (!instanceId) return;
    setIsLoading(true);
    setLoadError(false);
    try {
      const response = await instanceChannelService.listChannels(instanceId);
      setChannels(response.items);
    } catch {
      setLoadError(true);
      messageApi?.error(t('tenant.instances.channels.fetchError'));
    } finally {
      setIsLoading(false);
    }
  }, [instanceId, messageApi, t]);

  useEffect(() => {
    void fetchChannels();
  }, [fetchChannels]);

  const filteredChannels = useMemo(() => {
    if (!search) return channels;
    const q = search.toLowerCase();
    return channels.filter(
      (c) => c.name.toLowerCase().includes(q) || c.channel_type.toLowerCase().includes(q)
    );
  }, [channels, search]);

  const handleOpenModal = useCallback((channel?: ChannelConfig) => {
    if (channel) {
      setEditingChannel(channel);
      setFormChannelType(channel.channel_type);
      setFormName(channel.name);
      setFormConfig(channel.config);
    } else {
      setEditingChannel(null);
      setFormChannelType('mcp');
      setFormName('');
      setFormConfig({});
    }
    setIsModalOpen(true);
  }, []);

  const handleCloseModal = useCallback(() => {
    setIsModalOpen(false);
    setEditingChannel(null);
    setFormChannelType('mcp');
    setFormName('');
    setFormConfig({});
  }, []);

  const handleSaveChannel = useCallback(async () => {
    if (!instanceId || !formName.trim()) return;
    const typeOption = CHANNEL_TYPE_OPTIONS.find((o) => o.value === formChannelType);
    if (!editingChannel && typeOption && !typeOption.implemented) {
      messageApi?.error(
        t('tenant.instances.channels.typeNotSupported', 'Channel type not supported yet')
      );
      return;
    }
    setIsSubmitting(true);
    try {
      if (editingChannel) {
        await instanceChannelService.updateChannel(instanceId, editingChannel.id, {
          name: formName,
          config: formConfig,
        });
      } else {
        await instanceChannelService.createChannel(instanceId, {
          channel_type: formChannelType,
          name: formName,
          config: formConfig,
        });
      }

      messageApi?.success(
        editingChannel
          ? t('tenant.instances.channels.updateSuccess')
          : t('tenant.instances.channels.createSuccess')
      );
      handleCloseModal();
      void fetchChannels();
    } catch {
      messageApi?.error(t('tenant.instances.channels.saveError'));
    } finally {
      setIsSubmitting(false);
    }
  }, [
    instanceId,
    editingChannel,
    formChannelType,
    formName,
    formConfig,
    messageApi,
    t,
    handleCloseModal,
    fetchChannels,
  ]);

  const handleDeleteChannel = useCallback(
    async (channelId: string) => {
      if (!instanceId) return;
      setIsSubmitting(true);
      try {
        await instanceChannelService.deleteChannel(instanceId, channelId);
        messageApi?.success(t('tenant.instances.channels.deleteSuccess'));
        void fetchChannels();
      } catch {
        messageApi?.error(t('tenant.instances.channels.deleteError'));
      } finally {
        setIsSubmitting(false);
      }
    },
    [instanceId, messageApi, t, fetchChannels]
  );

  const handleTestConnection = useCallback(
    async (channelId: string) => {
      if (!instanceId) return;
      setTestingChannelId(channelId);
      try {
        const result = await instanceChannelService.testConnection(instanceId, channelId);
        if (result.status === 'ok') {
          messageApi?.success(result.message || t('tenant.instances.channels.testSuccess'));
        } else {
          messageApi?.error(result.message || t('tenant.instances.channels.testError'));
        }
        void fetchChannels();
      } catch {
        messageApi?.error(t('tenant.instances.channels.testError'));
      } finally {
        setTestingChannelId(null);
      }
    },
    [instanceId, messageApi, t, fetchChannels]
  );

  const getChannelTypeInfo = useCallback((type: ChannelType) => {
    return CHANNEL_TYPE_OPTIONS.find((o) => o.value === type) ?? DEFAULT_CHANNEL_TYPE_OPTION;
  }, []);

  const columns: ColumnsType<ChannelConfig> = [
    {
      title: t('tenant.instances.channels.colName'),
      key: 'name',
      ellipsis: true,
      render: (_, channel) => {
        const typeInfo = getChannelTypeInfo(channel.channel_type);
        return (
          <div className="flex items-center gap-3 overflow-hidden">
            <div className="shrink-0 w-10 h-10 rounded-lg bg-info-bg dark:bg-info-bg-dark flex items-center justify-center">
              <typeInfo.icon size={16} className="text-info-dark dark:text-info-light" />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-medium text-text-primary dark:text-text-inverse truncate">
                {channel.name}
              </p>
            </div>
          </div>
        );
      },
    },
    {
      title: t('tenant.instances.channels.colType'),
      key: 'type',
      render: (_, channel) => {
        const typeInfo = getChannelTypeInfo(channel.channel_type);
        return <Tag>{t(typeInfo.labelKey)}</Tag>;
      },
    },
    {
      title: t('tenant.instances.channels.colStatus'),
      key: 'status',
      render: (_, channel) => (
        <Tag color={STATUS_COLORS[channel.status]}>
          {t(`tenant.instances.channels.status.${channel.status}`, channel.status)}
        </Tag>
      ),
    },
    {
      title: t('tenant.instances.channels.colLastConnected'),
      key: 'last_connected_at',
      render: (_, channel) =>
        channel.last_connected_at ? formatDate(channel.last_connected_at) : '-',
    },
    {
      title: t('tenant.instances.channels.colActions'),
      key: 'actions',
      align: 'right',
      render: (_, channel) => (
        <Space size="small">
          <LazyButton
            type="link"
            size="small"
            onClick={() => {
              void handleTestConnection(channel.id);
            }}
            loading={testingChannelId === channel.id}
            className="p-0"
          >
            {t('tenant.instances.channels.testConnection')}
          </LazyButton>
          <LazyButton
            type="link"
            size="small"
            onClick={() => {
              handleOpenModal(channel);
            }}
            className="p-0"
          >
            {t('common.edit')}
          </LazyButton>
          <LazyPopconfirm
            title={t('tenant.instances.channels.deleteConfirm')}
            onConfirm={() => {
              void handleDeleteChannel(channel.id);
            }}
            okText={t('common.confirm')}
            cancelText={t('common.cancel')}
          >
            <LazyButton type="link" danger size="small" disabled={isSubmitting} className="p-0">
              {t('common.delete')}
            </LazyButton>
          </LazyPopconfirm>
        </Space>
      ),
    },
  ];

  const renderConfigFields = useCallback(() => {
    switch (formChannelType) {
      case 'mcp':
        return (
          <>
            <div>
              <label
                htmlFor="mcp-server-url"
                className="block text-sm font-medium text-text-secondary dark:text-text-muted-light mb-1"
              >
                {t('tenant.instances.channels.config.serverUrl')}
              </label>
              <Input
                id="mcp-server-url"
                type="url"
                inputMode="url"
                name="server_url"
                autoComplete="off"
                spellCheck={false}
                value={(formConfig.server_url as string) || ''}
                onChange={(e) => {
                  setFormConfig({ ...formConfig, server_url: e.target.value });
                }}
                placeholder={t('tenant.instances.channels.config.serverUrlPlaceholder')}
              />
            </div>
            <div>
              <label
                htmlFor="mcp-timeout"
                className="block text-sm font-medium text-text-secondary dark:text-text-muted-light mb-1"
              >
                {t('tenant.instances.channels.config.timeout')}
              </label>
              <InputNumber
                id="mcp-timeout"
                value={(formConfig.timeout as number) || 30}
                onChange={(val) => {
                  setFormConfig({ ...formConfig, timeout: val || 30 });
                }}
                min={1}
                max={300}
                className="w-full"
              />
            </div>
          </>
        );
      case 'webhook':
        return (
          <>
            <div>
              <label
                htmlFor="webhook-url"
                className="block text-sm font-medium text-text-secondary dark:text-text-muted-light mb-1"
              >
                {t('tenant.instances.channels.config.url')}
              </label>
              <Input
                id="webhook-url"
                type="url"
                inputMode="url"
                name="url"
                autoComplete="off"
                spellCheck={false}
                value={(formConfig.url as string) || ''}
                onChange={(e) => {
                  setFormConfig({ ...formConfig, url: e.target.value });
                }}
                placeholder={t('tenant.instances.channels.config.webhookUrlPlaceholder')}
              />
            </div>
            <div>
              <label
                htmlFor="webhook-secret"
                className="block text-sm font-medium text-text-secondary dark:text-text-muted-light mb-1"
              >
                {t('tenant.instances.channels.config.secret')}
              </label>
              <Input.Password
                id="webhook-secret"
                autoComplete="off"
                spellCheck={false}
                value={(formConfig.secret as string) || ''}
                onChange={(e) => {
                  setFormConfig({ ...formConfig, secret: e.target.value });
                }}
                placeholder={t('tenant.instances.channels.config.secretPlaceholder')}
              />
            </div>
          </>
        );
      case 'api':
        return (
          <>
            <div>
              <label
                htmlFor="api-base-url"
                className="block text-sm font-medium text-text-secondary dark:text-text-muted-light mb-1"
              >
                {t('tenant.instances.channels.config.baseUrl')}
              </label>
              <Input
                id="api-base-url"
                type="url"
                inputMode="url"
                name="base_url"
                autoComplete="off"
                spellCheck={false}
                value={(formConfig.base_url as string) || ''}
                onChange={(e) => {
                  setFormConfig({ ...formConfig, base_url: e.target.value });
                }}
                placeholder={t('tenant.instances.channels.config.apiBaseUrlPlaceholder')}
              />
            </div>
            <div>
              <label
                htmlFor="api-key"
                className="block text-sm font-medium text-text-secondary dark:text-text-muted-light mb-1"
              >
                {t('tenant.instances.channels.config.apiKey')}
              </label>
              <Input.Password
                id="api-key"
                autoComplete="off"
                spellCheck={false}
                value={(formConfig.api_key as string) || ''}
                onChange={(e) => {
                  setFormConfig({ ...formConfig, api_key: e.target.value });
                }}
                placeholder={t('tenant.instances.channels.config.apiKeyPlaceholder')}
              />
            </div>
          </>
        );
      default:
        return (
          <div className="text-sm text-text-muted dark:text-text-muted italic">
            {t('tenant.instances.channels.configNotAvailable')}
          </div>
        );
    }
  }, [formChannelType, formConfig, t]);

  if (!instanceId) return null;

  return (
    <div className="flex flex-col gap-6">
      {/* Toolbar */}
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-text-primary dark:text-text-inverse">
            {t('tenant.instances.channels.title')}
          </h2>
          <p className="text-sm text-text-muted">{t('tenant.instances.channels.description')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <LazyButton
            icon={<RefreshCw size={16} />}
            onClick={() => {
              void fetchChannels();
            }}
            loading={isLoading}
            aria-label={t('common.refresh', 'Refresh')}
          >
            {t('common.refresh', 'Refresh')}
          </LazyButton>
          <LazyButton
            type="primary"
            icon={<Plus size={16} />}
            onClick={() => {
              handleOpenModal();
            }}
          >
            {t('tenant.instances.channels.addChannel')}
          </LazyButton>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 mb-6">
        <div className="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-info-bg dark:bg-info-bg-dark rounded-lg">
              <Network size={16} className="text-info-dark dark:text-info-light" />
            </div>
            <div>
              <p className="text-2xl font-semibold tabular-nums text-text-primary dark:text-text-inverse">
                {channels.length}
              </p>
              <p className="text-xs text-text-muted dark:text-text-muted">
                {t('tenant.instances.channels.totalChannels')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-success-bg dark:bg-success-bg-dark rounded-lg">
              <Link size={16} className="text-success-dark dark:text-success-light" />
            </div>
            <div>
              <p className="text-2xl font-semibold tabular-nums text-text-primary dark:text-text-inverse">
                {channels.filter((c) => c.status === 'connected').length}
              </p>
              <p className="text-xs text-text-muted dark:text-text-muted">
                {t('tenant.instances.channels.connected')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-gray-100 dark:bg-gray-900/30 rounded-lg">
              <Unlink size={16} className="text-gray-600 dark:text-gray-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold tabular-nums text-text-primary dark:text-text-inverse">
                {
                  channels.filter((c) => c.status === 'disconnected' || c.status === 'pending')
                    .length
                }
              </p>
              <p className="text-xs text-text-muted dark:text-text-muted">
                {t('tenant.instances.channels.disconnected')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-error-bg dark:bg-error-bg-dark rounded-lg">
              <AlertCircle size={16} className="text-error-dark dark:text-error-light" />
            </div>
            <div>
              <p className="text-2xl font-semibold tabular-nums text-text-primary dark:text-text-inverse">
                {channels.filter((c) => c.status === 'error').length}
              </p>
              <p className="text-xs text-text-muted dark:text-text-muted">
                {t('tenant.instances.channels.error')}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Search */}
      <div className="mb-4">
        <Search
          placeholder={t('tenant.instances.channels.searchPlaceholder')}
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
          }}
          allowClear
          enterButton={
            <>
              <span className="sr-only">{t('common.search', 'Search')}</span>
              <SearchIcon size={16} aria-hidden="true" />
            </>
          }
          className="w-full max-w-sm"
        />
      </div>

      {/* Channels Table */}
      <div className="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark overflow-hidden">
        {isLoading ? (
          <SkeletonLoader type="table" rows={5} />
        ) : loadError ? (
          <div className="py-20 flex flex-col items-center gap-4">
            <LazyAlert
              type="error"
              showIcon
              message={t('tenant.instances.channels.fetchError')}
              className="max-w-md"
            />
            <LazyButton
              onClick={() => {
                void fetchChannels();
              }}
            >
              {t('common.retry', 'Retry')}
            </LazyButton>
          </div>
        ) : filteredChannels.length === 0 ? (
          <div className="py-20">
            <LazyEmpty description={t('tenant.instances.channels.noChannels')} />
          </div>
        ) : (
          <Table
            columns={columns}
            dataSource={filteredChannels}
            rowKey="id"
            pagination={{ pageSize: 20, hideOnSinglePage: true, showSizeChanger: false }}
            scroll={{ x: 'max-content' }}
            className="max-w-full"
          />
        )}
      </div>

      {/* Add/Edit Channel Modal */}
      <LazyModal
        title={
          editingChannel
            ? t('tenant.instances.channels.editChannel')
            : t('tenant.instances.channels.addChannel')
        }
        open={isModalOpen}
        onOk={() => {
          void handleSaveChannel();
        }}
        onCancel={handleCloseModal}
        confirmLoading={isSubmitting}
        okButtonProps={{ disabled: !formName.trim() }}
        width={500}
      >
        <div className="space-y-4 py-2">
          <div>
            <label
              htmlFor="channel-name"
              className="block text-sm font-medium text-text-secondary dark:text-text-muted-light mb-1"
            >
              {t('tenant.instances.channels.channelName')}
            </label>
            <Input
              id="channel-name"
              value={formName}
              onChange={(e) => {
                setFormName(e.target.value);
              }}
              placeholder={t('tenant.instances.channels.channelNamePlaceholder')}
            />
          </div>
          <div>
            <label
              htmlFor="channel-type"
              className="block text-sm font-medium text-text-secondary dark:text-text-muted-light mb-1"
            >
              {t('tenant.instances.channels.channelType')}
            </label>
            <LazySelect
              id="channel-type"
              value={formChannelType}
              onChange={(val: ChannelType) => {
                setFormChannelType(val);
                setFormConfig({});
              }}
              options={CHANNEL_TYPE_OPTIONS.map((o) => ({
                value: o.value,
                disabled: !o.implemented,
                label: (
                  <span className="flex items-center gap-2">
                    <o.icon size={16} />
                    {t(o.labelKey)}
                    {!o.implemented && (
                      <span className="text-xs text-text-muted">
                        {t('tenant.instances.channels.typeComingSoon', 'Coming soon')}
                      </span>
                    )}
                  </span>
                ),
              }))}
              className="w-full"
              disabled={!!editingChannel}
            />
          </div>
          <div className="border-t border-border-light dark:border-border-separator pt-4">
            <h4 className="text-sm font-medium text-text-secondary dark:text-text-muted-light mb-3">
              {t('tenant.instances.channels.config.title')}
            </h4>
            {renderConfigFields()}
          </div>
        </div>
      </LazyModal>
    </div>
  );
};
