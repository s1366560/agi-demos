import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';

import { Input, Tag, Button as AntButton, Select, InputNumber } from 'antd';
import { AlertCircle, ArrowLeft, Link, Network, Plus, Unlink, Webhook, Plug, MessageCircle, MessageSquare, Mail } from 'lucide-react';

import { instanceChannelService } from '@/services/instanceChannelService';

import {
  useLazyMessage,
  LazyPopconfirm,
  LazyEmpty,
  LazySpin,
  LazyModal,
} from '@/components/ui/lazyAntd';

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

const CHANNEL_TYPE_OPTIONS: { value: ChannelType; label: string; icon: any }[] = [
  { value: 'mcp', label: 'MCP Server', icon: Network },
  { value: 'webhook', label: 'Webhook', icon: Webhook },
  { value: 'websocket', label: 'WebSocket', icon: Link },
  { value: 'api', label: 'REST API', icon: Plug },
  { value: 'slack', label: 'Slack', icon: MessageCircle },
  { value: 'discord', label: 'Discord', icon: MessageSquare },
  { value: 'email', label: 'Email', icon: Mail },
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
  const navigate = useNavigate();
  const message = useLazyMessage();

  const [isLoading, setIsLoading] = useState(false);
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
    try {
      const response = await instanceChannelService.listChannels(instanceId);
      setChannels(response.items);
    } catch (error) {
      console.error('Failed to fetch channels:', error);
      message?.error(t('tenant.instances.channels.fetchError'));
    } finally {
      setIsLoading(false);
    }
  }, [instanceId, message, t]);

  useEffect(() => {
    fetchChannels();
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

      message?.success(
        editingChannel
          ? t('tenant.instances.channels.updateSuccess')
          : t('tenant.instances.channels.createSuccess')
      );
      handleCloseModal();
      fetchChannels();
    } catch (error) {
      console.error('Failed to save channel:', error);
      message?.error(t('tenant.instances.channels.saveError'));
    } finally {
      setIsSubmitting(false);
    }
  }, [
    instanceId,
    editingChannel,
    formChannelType,
    formName,
    formConfig,
    message,
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
        message?.success(t('tenant.instances.channels.deleteSuccess'));
        fetchChannels();
      } catch (error) {
        console.error('Failed to delete channel:', error);
        message?.error(t('tenant.instances.channels.deleteError'));
      } finally {
        setIsSubmitting(false);
      }
    },
    [instanceId, message, t, fetchChannels]
  );

  const handleTestConnection = useCallback(
    async (channelId: string) => {
      if (!instanceId) return;
      setTestingChannelId(channelId);
      try {
        const result = await instanceChannelService.testConnection(instanceId, channelId);
        message?.success(result.message || t('tenant.instances.channels.testSuccess'));
        fetchChannels();
      } catch (error) {
        console.error('Channel test failed:', error);
        message?.error(t('tenant.instances.channels.testError'));
      } finally {
        setTestingChannelId(null);
      }
    },
    [instanceId, message, t, fetchChannels]
  );

  const handleGoBack = useCallback(() => {
    navigate(-1);
  }, [navigate]);

  const getChannelTypeInfo = useCallback((type: ChannelType) => {
    return CHANNEL_TYPE_OPTIONS.find((o) => o.value === type) || CHANNEL_TYPE_OPTIONS[0];
  }, []);

  const renderConfigFields = useCallback(() => {
    switch (formChannelType) {
      case 'mcp':
        return (
          <>
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                {t('tenant.instances.channels.config.serverUrl')}
              </label>
              <Input
                value={(formConfig.server_url as string) || ''}
                onChange={(e) => {
                  setFormConfig({ ...formConfig, server_url: e.target.value });
                }}
                placeholder="ws://localhost:8080"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                {t('tenant.instances.channels.config.timeout')}
              </label>
              <InputNumber
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
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                {t('tenant.instances.channels.config.url')}
              </label>
              <Input
                value={(formConfig.url as string) || ''}
                onChange={(e) => {
                  setFormConfig({ ...formConfig, url: e.target.value });
                }}
                placeholder="https://example.com/webhook"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                {t('tenant.instances.channels.config.secret')}
              </label>
              <Input.Password
                value={(formConfig.secret as string) || ''}
                onChange={(e) => {
                  setFormConfig({ ...formConfig, secret: e.target.value });
                }}
                placeholder="********"
              />
            </div>
          </>
        );
      case 'api':
        return (
          <>
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                {t('tenant.instances.channels.config.baseUrl')}
              </label>
              <Input
                value={(formConfig.base_url as string) || ''}
                onChange={(e) => {
                  setFormConfig({ ...formConfig, base_url: e.target.value });
                }}
                placeholder="https://api.example.com"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                {t('tenant.instances.channels.config.apiKey')}
              </label>
              <Input.Password
                value={(formConfig.api_key as string) || ''}
                onChange={(e) => {
                  setFormConfig({ ...formConfig, api_key: e.target.value });
                }}
                placeholder="********"
              />
            </div>
          </>
        );
      default:
        return (
          <div className="text-sm text-slate-500 dark:text-slate-400 italic">
            {t('tenant.instances.channels.configNotAvailable')}
          </div>
        );
    }
  }, [formChannelType, formConfig, t]);

  if (!instanceId) return null;

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <button
          onClick={handleGoBack}
          type="button"
          className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 mb-3"
        >
          <ArrowLeft size={16} />
          {t('common.back')}
        </button>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
              {t('tenant.instances.channels.title')}
            </h1>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {t('tenant.instances.channels.description')}
            </p>
          </div>
          <button
            onClick={() => {
              handleOpenModal();
            }}
            type="button"
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium"
          >
            <Plus size={16} />
            {t('tenant.instances.channels.addChannel')}
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 mb-6">
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg">
              <Network size={16} className="text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
                {channels.length}
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.instances.channels.totalChannels')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-green-100 dark:bg-green-900/30 rounded-lg">
              <Link size={16} className="text-green-600 dark:text-green-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
                {channels.filter((c) => c.status === 'connected').length}
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.instances.channels.connected')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-gray-100 dark:bg-gray-900/30 rounded-lg">
              <Unlink size={16} className="text-gray-600 dark:text-gray-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
                {channels.filter((c) => c.status === 'disconnected' || c.status === 'pending').length}
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.instances.channels.disconnected')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-red-100 dark:bg-red-900/30 rounded-lg">
              <AlertCircle size={16} className="text-red-600 dark:text-red-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
                {channels.filter((c) => c.status === 'error').length}
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
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
          className="max-w-sm"
        />
      </div>

      {/* Channels Table */}
      <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <LazySpin size="large" />
          </div>
        ) : filteredChannels.length === 0 ? (
          <div className="py-20">
            <LazyEmpty description={t('tenant.instances.channels.noChannels')} />
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.instances.channels.colName')}
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.instances.channels.colType')}
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.instances.channels.colStatus')}
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.instances.channels.colLastConnected')}
                </th>
                <th className="text-right px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.instances.channels.colActions')}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
              {filteredChannels.map((channel) => {
                const typeInfo = getChannelTypeInfo(channel.channel_type)!;
                return (
                  <tr
                    key={channel.id}
                    className="hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-lg bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
                          <typeInfo.icon size={16} className="text-blue-600 dark:text-blue-400" />
                        </div>
                        <div>
                          <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                            {channel.name}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <Tag>{typeInfo.label}</Tag>
                    </td>
                    <td className="px-4 py-3">
                      <Tag color={STATUS_COLORS[channel.status]}>
                        {t(`tenant.instances.channels.status.${channel.status}`, channel.status)}
                      </Tag>
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-500 dark:text-slate-400">
                      {channel.last_connected_at
                        ? new Date(channel.last_connected_at).toLocaleString()
                        : '-'}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <AntButton
                          type="link"
                          size="small"
                          onClick={() => handleTestConnection(channel.id)}
                          loading={testingChannelId === channel.id}
                          className="p-0"
                        >
                          {t('tenant.instances.channels.testConnection')}
                        </AntButton>
                        <AntButton
                          type="link"
                          size="small"
                          onClick={() => {
                            handleOpenModal(channel);
                          }}
                          className="p-0"
                        >
                          {t('common.edit')}
                        </AntButton>
                        <LazyPopconfirm
                          title={t('tenant.instances.channels.deleteConfirm')}
                          onConfirm={() => handleDeleteChannel(channel.id)}
                          okText={t('common.confirm')}
                          cancelText={t('common.cancel')}
                        >
                          <button
                            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-md transition-colors"
                            type="button"
                            disabled={isSubmitting}
                          >
                            {t('common.delete')}
                          </button>
                        </LazyPopconfirm>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
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
        onOk={handleSaveChannel}
        onCancel={handleCloseModal}
        confirmLoading={isSubmitting}
        okButtonProps={{ disabled: !formName.trim() }}
        width={500}
      >
        <div className="space-y-4 py-2">
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              {t('tenant.instances.channels.channelName')}
            </label>
            <Input
              value={formName}
              onChange={(e) => {
                setFormName(e.target.value);
              }}
              placeholder={t('tenant.instances.channels.channelNamePlaceholder')}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              {t('tenant.instances.channels.channelType')}
            </label>
            <Select
              value={formChannelType}
              onChange={(val) => {
                setFormChannelType(val);
                setFormConfig({});
              }}
              options={CHANNEL_TYPE_OPTIONS.map((o) => ({
                value: o.value,
                label: (
                  <span className="flex items-center gap-2">
                    <o.icon size={16} />
                    {o.label}
                  </span>
                ),
              }))}
              className="w-full"
              disabled={!!editingChannel}
            />
          </div>
          <div className="border-t border-slate-200 dark:border-slate-600 pt-4">
            <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-3">
              {t('tenant.instances.channels.config.title')}
            </h4>
            {renderConfigFields()}
          </div>
        </div>
      </LazyModal>
    </div>
  );
};
