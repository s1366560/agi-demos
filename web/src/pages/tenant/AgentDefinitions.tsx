import { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Badge, Card, Dropdown, message, Spin, Switch, Tag, Tooltip } from 'antd';
import { Bot, Edit2, MoreVertical, Plus, RefreshCw, Search, Trash2 } from 'lucide-react';

import { AgentDefinitionModal } from '../../components/agent/AgentDefinitionModal';
import {
  filterDefinitions,
  useClearDefinitionError,
  useDefinitionError,
  useDefinitionFilters,
  useDefinitionLoading,
  useDefinitions,
  useDeleteDefinition,
  useEnabledDefinitionsCount,
  useListDefinitions,
  useSetDefinitionFilters,
  useToggleDefinitionEnabled,
} from '../../stores/agentDefinitions';

import type { AgentDefinition } from '../../types/multiAgent';
import type { MenuProps } from 'antd';

type StatusFilter = 'all' | 'enabled' | 'disabled';
type SortField = 'name' | 'recent' | 'invocations';

const SORT_FNS: Record<SortField, (a: AgentDefinition, b: AgentDefinition) => number> = {
  name: (a, b) => (a.display_name ?? a.name).localeCompare(b.display_name ?? b.name),
  invocations: (a, b) => b.total_invocations - a.total_invocations,
  recent: (a, b) =>
    new Date(b.updated_at ?? b.created_at).getTime() -
    new Date(a.updated_at ?? a.created_at).getTime(),
};

export const AgentDefinitions: React.FC = () => {
  const { t } = useTranslation();

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [sortField, setSortField] = useState<SortField>('name');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingDef, setEditingDef] = useState<AgentDefinition | null>(null);

  const definitions = useDefinitions();
  const filters = useDefinitionFilters();
  const isLoading = useDefinitionLoading();
  const error = useDefinitionError();
  const enabledCount = useEnabledDefinitionsCount();

  const listDefinitions = useListDefinitions();
  const deleteDefinition = useDeleteDefinition();
  const toggleEnabled = useToggleDefinitionEnabled();
  const setFilters = useSetDefinitionFilters();
  const clearError = useClearDefinitionError();

  const filteredDefinitions = useMemo(() => {
    const filtered = filterDefinitions(definitions, {
      ...filters,
      search,
      enabled: statusFilter === 'all' ? null : statusFilter === 'enabled',
    });
    return [...filtered].sort(SORT_FNS[sortField]);
  }, [definitions, filters, search, statusFilter, sortField]);

  useEffect(() => {
    listDefinitions();
  }, [listDefinitions]);

  useEffect(() => {
    setFilters({
      search,
      enabled: statusFilter === 'all' ? null : statusFilter === 'enabled',
    });
  }, [search, statusFilter, setFilters]);

  useEffect(() => {
    if (error) message.error(error);
  }, [error]);

  useEffect(
    () => () => {
      clearError();
    },
    [clearError]
  );

  const handleCreate = useCallback(() => {
    setEditingDef(null);
    setIsModalOpen(true);
  }, []);

  const handleEdit = useCallback((def: AgentDefinition) => {
    setEditingDef(def);
    setIsModalOpen(true);
  }, []);

  const handleToggle = useCallback(
    async (id: string, enabled: boolean) => {
      try {
        await toggleEnabled(id, enabled);
        message.success(enabled ? 'Agent enabled' : 'Agent disabled');
      } catch {
        // Error handled by store
      }
    },
    [toggleEnabled]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteDefinition(id);
        message.success('Agent definition deleted');
      } catch {
        // Error handled by store
      }
    },
    [deleteDefinition]
  );

  const handleRefresh = useCallback(() => listDefinitions(), [listDefinitions]);

  const handleModalClose = useCallback(() => {
    setIsModalOpen(false);
    setEditingDef(null);
  }, []);

  const handleModalSuccess = useCallback(() => {
    setIsModalOpen(false);
    setEditingDef(null);
    listDefinitions();
  }, [listDefinitions]);

  const getCardMenuItems = useCallback(
    (def: AgentDefinition): MenuProps['items'] => [
      {
        key: 'edit',
        label: t('common.edit', 'Edit'),
        icon: <Edit2 size={14} />,
        onClick: () => {
          handleEdit(def);
        },
      },
      { type: 'divider' },
      {
        key: 'delete',
        label: t('common.delete', 'Delete'),
        icon: <Trash2 size={14} />,
        danger: true,
        onClick: () => handleDelete(def.id),
      },
    ],
    [handleEdit, handleDelete, t]
  );

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-5 p-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            {t('tenant.agentDefinitions.title', 'Agent Definitions')}
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            {t(
              'tenant.agentDefinitions.subtitle',
              'Configure and manage AI agent definitions for your tenant'
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={handleCreate}
          className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-white text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors"
        >
          <Plus size={16} />
          {t('tenant.agentDefinitions.createNew', 'Create Agent')}
        </button>
      </div>

      {/* Stats bar */}
      <div className="flex items-center gap-4 text-sm text-slate-600 dark:text-slate-400">
        <span>
          {definitions.length} {definitions.length === 1 ? 'agent' : 'agents'}
        </span>
        <span className="text-slate-300 dark:text-slate-600">|</span>
        <span>{enabledCount} enabled</span>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
          <input
            type="text"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
            }}
            placeholder={t('common.search', 'Search...')}
            className="w-full pl-9 pr-3 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-primary/30 focus:border-primary outline-none"
          />
        </div>

        <div className="flex items-center gap-2">
          {(['all', 'enabled', 'disabled'] as StatusFilter[]).map((sf) => (
            <button
              key={sf}
              type="button"
              onClick={() => {
                setStatusFilter(sf);
              }}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                statusFilter === sf
                  ? 'bg-primary text-white'
                  : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600'
              }`}
            >
              {sf.charAt(0).toUpperCase() + sf.slice(1)}
            </button>
          ))}
        </div>

        <select
          value={sortField}
          onChange={(e) => {
            setSortField(e.target.value as SortField);
          }}
          className="px-3 py-1.5 text-xs border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300"
        >
          <option value="name">Name</option>
          <option value="recent">Recent</option>
          <option value="invocations">Invocations</option>
        </select>

        <button
          type="button"
          onClick={handleRefresh}
          className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
        >
          <RefreshCw size={16} />
        </button>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Spin size="large" />
        </div>
      ) : filteredDefinitions.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-slate-500 dark:text-slate-400">
          <Bot size={48} className="mb-4 text-slate-300 dark:text-slate-600" />
          <p className="text-lg font-medium">
            {search || statusFilter !== 'all'
              ? t('tenant.agentDefinitions.noResults', 'No agents match your filters')
              : t('tenant.agentDefinitions.empty', 'No agent definitions yet')}
          </p>
          {!search && statusFilter === 'all' && (
            <button
              type="button"
              onClick={handleCreate}
              className="mt-4 text-primary hover:underline text-sm"
            >
              {t('tenant.agentDefinitions.createFirst', 'Create your first agent')}
            </button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filteredDefinitions.map((def) => (
            <Card
              key={def.id}
              size="small"
              className="hover:shadow-md transition-shadow dark:bg-slate-800 dark:border-slate-700"
              title={
                <div className="flex items-center gap-2 min-w-0">
                  <Badge status={def.enabled ? 'success' : 'default'} className="flex-shrink-0" />
                  <Tooltip title={def.display_name ?? def.name}>
                    <span className="truncate font-medium text-sm">
                      {def.display_name ?? def.name}
                    </span>
                  </Tooltip>
                </div>
              }
              extra={
                <div className="flex items-center gap-2">
                  <Switch
                    size="small"
                    checked={def.enabled}
                    onChange={(checked) => handleToggle(def.id, checked)}
                  />
                  <Dropdown menu={{ items: getCardMenuItems(def) ?? [] }} trigger={['click']}>
                    <button
                      type="button"
                      className="p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                    >
                      <MoreVertical size={14} />
                    </button>
                  </Dropdown>
                </div>
              }
            >
              <div className="space-y-2">
                <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2">
                  {def.system_prompt
                    ? def.system_prompt.substring(0, 120) +
                      (def.system_prompt.length > 120 ? '...' : '')
                    : 'No system prompt'}
                </p>

                <div className="flex flex-wrap gap-1">
                  {def.model && <Tag className="text-[10px]">{def.model}</Tag>}
                  {def.can_spawn && (
                    <Tag color="blue" className="text-[10px]">
                      Spawn
                    </Tag>
                  )}
                  {def.agent_to_agent_enabled && (
                    <Tag color="green" className="text-[10px]">
                      A2A
                    </Tag>
                  )}
                  {def.source === 'filesystem' && (
                    <Tag color="orange" className="text-[10px]">
                      FS
                    </Tag>
                  )}
                </div>

                <div className="flex items-center justify-between text-[11px] text-slate-400 dark:text-slate-500 pt-1 border-t border-slate-100 dark:border-slate-700">
                  <span>{def.total_invocations} invocations</span>
                  {def.success_rate !== null && (
                    <span>{Math.round(def.success_rate * 100)}% success</span>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Modal */}
      <AgentDefinitionModal
        isOpen={isModalOpen}
        onClose={handleModalClose}
        onSuccess={handleModalSuccess}
        definition={editingDef}
      />
    </div>
  );
};

export default AgentDefinitions;
