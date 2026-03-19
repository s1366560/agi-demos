import { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { message, Popconfirm, Spin, Switch, Table, Tag } from 'antd';
import { Link, Plus, RefreshCw, Search } from 'lucide-react';

import { AgentBindingModal } from '../../components/agent/AgentBindingModal';
import {
  useBindingError,
  useBindingLoading,
  useBindings,
  useClearBindingError,
  useDeleteBinding,
  useListBindings,
  useToggleBinding,
} from '../../stores/agentBindings';
import { useDefinitions, useListDefinitions } from '../../stores/agentDefinitions';

import type { AgentBinding } from '../../types/multiAgent';
import type { ColumnsType } from 'antd/es/table';

export const AgentBindings: React.FC = () => {
  const { t } = useTranslation();

  const [search, setSearch] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);

  const bindings = useBindings();
  const isLoading = useBindingLoading();
  const error = useBindingError();

  const listBindings = useListBindings();
  const deleteBinding = useDeleteBinding();
  const toggleBinding = useToggleBinding();
  const clearError = useClearBindingError();

  const definitions = useDefinitions();
  const listDefinitions = useListDefinitions();

  const defNameMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const d of definitions) {
      map.set(d.id, d.display_name ?? d.name);
    }
    return map;
  }, [definitions]);

  const filteredBindings = useMemo(() => {
    if (!search) return bindings;
    const lower = search.toLowerCase();
    return bindings.filter((b) => {
      const agentName = defNameMap.get(b.agent_id) ?? b.agent_id;
      return (
        agentName.toLowerCase().includes(lower) ||
        (b.channel_type ?? '').toLowerCase().includes(lower) ||
        (b.channel_id ?? '').toLowerCase().includes(lower)
      );
    });
  }, [bindings, search, defNameMap]);

  useEffect(() => {
    listBindings();
    listDefinitions();
  }, [listBindings, listDefinitions]);

  useEffect(() => {
    if (error) message.error(error);
  }, [error]);

  useEffect(
    () => () => {
      clearError();
    },
    [clearError]
  );

  const handleToggle = useCallback(
    async (id: string, enabled: boolean) => {
      try {
        await toggleBinding(id, enabled);
        message.success(enabled ? 'Binding enabled' : 'Binding disabled');
      } catch {
        // handled by store
      }
    },
    [toggleBinding]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteBinding(id);
        message.success('Binding deleted');
      } catch {
        // handled by store
      }
    },
    [deleteBinding]
  );

  const handleRefresh = useCallback(() => listBindings(), [listBindings]);

  const handleModalClose = useCallback(() => {
    setIsModalOpen(false);
  }, []);

  const handleModalSuccess = useCallback(() => {
    setIsModalOpen(false);
    listBindings();
  }, [listBindings]);

  const columns: ColumnsType<AgentBinding> = useMemo(
    () => [
      {
        title: t('tenant.agentBindings.columns.agent', 'Agent'),
        dataIndex: 'agent_id',
        key: 'agent',
        render: (agentId: string) => (
          <span className="font-medium text-sm">{defNameMap.get(agentId) ?? agentId}</span>
        ),
      },
      {
        title: t('tenant.agentBindings.columns.channelType', 'Channel Type'),
        dataIndex: 'channel_type',
        key: 'channel_type',
        render: (val: string | null) =>
          val ? <Tag>{val}</Tag> : <Tag color="default">Any</Tag>,
      },
      {
        title: t('tenant.agentBindings.columns.channelId', 'Channel ID'),
        dataIndex: 'channel_id',
        key: 'channel_id',
        render: (val: string | null) => (
          <span className="text-xs text-slate-500 dark:text-slate-400">{val ?? '-'}</span>
        ),
      },
      {
        title: t('tenant.agentBindings.columns.priority', 'Priority'),
        dataIndex: 'priority',
        key: 'priority',
        width: 90,
        align: 'center' as const,
        sorter: (a: AgentBinding, b: AgentBinding) => b.priority - a.priority,
      },
      {
        title: t('tenant.agentBindings.columns.enabled', 'Enabled'),
        dataIndex: 'enabled',
        key: 'enabled',
        width: 80,
        align: 'center' as const,
        render: (_: boolean, record: AgentBinding) => (
          <Switch
            size="small"
            checked={record.enabled}
            onChange={(checked) => handleToggle(record.id, checked)}
          />
        ),
      },
      {
        title: '',
        key: 'actions',
        width: 60,
        render: (_: unknown, record: AgentBinding) => (
          <Popconfirm
            title="Delete this binding?"
            onConfirm={() => handleDelete(record.id)}
            okText="Delete"
            cancelText="Cancel"
          >
            <button
              type="button"
              className="text-slate-400 hover:text-red-500 transition-colors text-xs"
            >
              {t('common.delete', 'Delete')}
            </button>
          </Popconfirm>
        ),
      },
    ],
    [defNameMap, handleToggle, handleDelete, t]
  );

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-5 p-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            {t('tenant.agentBindings.title', 'Agent Bindings')}
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            {t(
              'tenant.agentBindings.subtitle',
              'Bind agents to channels to control which agent handles which conversations'
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={() => { setIsModalOpen(true); }}
          className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-white text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors"
        >
          <Plus size={16} />
          {t('tenant.agentBindings.createNew', 'Create Binding')}
        </button>
      </div>

      <div className="flex items-center gap-4 text-sm text-slate-600 dark:text-slate-400">
        <span>
          {bindings.length} {bindings.length === 1 ? 'binding' : 'bindings'}
        </span>
      </div>

      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
        <div className="relative flex-1 max-w-sm">
          <Search
            className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
            size={16}
          />
          <input
            type="text"
            value={search}
            onChange={(e) => { setSearch(e.target.value); }}
            placeholder={t('common.search', 'Search...')}
            className="w-full pl-9 pr-3 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-primary/30 focus:border-primary outline-none"
          />
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
        >
          <RefreshCw size={16} />
        </button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Spin size="large" />
        </div>
      ) : filteredBindings.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-slate-500 dark:text-slate-400">
          <Link size={48} className="mb-4 text-slate-300 dark:text-slate-600" />
          <p className="text-lg font-medium">
            {search
              ? t('tenant.agentBindings.noResults', 'No bindings match your search')
              : t('tenant.agentBindings.empty', 'No agent bindings yet')}
          </p>
          {!search && (
            <button
              type="button"
              onClick={() => { setIsModalOpen(true); }}
              className="mt-4 text-primary hover:underline text-sm"
            >
              {t('tenant.agentBindings.createFirst', 'Create your first binding')}
            </button>
          )}
        </div>
      ) : (
        <Table<AgentBinding>
          dataSource={filteredBindings}
          columns={columns}
          rowKey="id"
          size="small"
          pagination={false}
          className="dark:[&_.ant-table]:bg-slate-800"
        />
      )}

      <AgentBindingModal
        isOpen={isModalOpen}
        onClose={handleModalClose}
        onSuccess={handleModalSuccess}
      />
    </div>
  );
};

export default AgentBindings;
