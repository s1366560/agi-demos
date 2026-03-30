/**
 * Dashboard Bindings Component
 *
 * Displays list of bindings with quick add/edit capabilities.
 */

import { memo, useEffect, useMemo, useState, useCallback } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Plus, RefreshCw, Route, Search } from 'lucide-react';

import {
  useBindings,
  useBindingLoading,
  useListBindings,
  useToggleBinding,
  useDeleteBinding,
} from '../../../stores/agentBindings';
import { useDefinitions, useListDefinitions } from '../../../stores/agentDefinitions';

import type { AgentBinding } from '../../../types/multiAgent';

// ============================================================================
// Binding Card Component
// ============================================================================

interface BindingCardProps {
  binding: AgentBinding;
  onToggle: (id: string, enabled: boolean) => void;
  onDelete: (id: string) => void;
  agentName: string;
}

const BindingCard: FC<BindingCardProps> = memo(({ binding, onToggle, onDelete, agentName }) => {
  return (
    <div
      className={`bg-white dark:bg-slate-800 border rounded-xl p-4 transition-[color,background-color,border-color,box-shadow,opacity,transform] ${
        binding.enabled
          ? 'border-blue-600 dark:border-blue-500 shadow-sm'
          : 'border-slate-200 dark:border-slate-700 opacity-70'
      }`}
    >
      <div className="flex items-start justify-between mb-3">
        <div>
          <h4 className="font-medium text-sm text-slate-900 dark:text-white">{agentName}</h4>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {binding.channel_type ?? 'Any Channel'}
          </p>
        </div>
        <label className="inline-flex relative items-center cursor-pointer">
          <input
            type="checkbox"
            checked={binding.enabled}
            onChange={(e) => {
              onToggle(binding.id, e.target.checked);
            }}
            aria-label={`Toggle ${agentName} binding`}
            className="sr-only peer"
          />
          <div className="w-9 h-5 bg-slate-300 dark:bg-slate-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-transform peer-checked:bg-blue-600" />
        </label>
      </div>

      <div className="space-y-1 text-xs text-slate-500 dark:text-slate-400">
        {binding.channel_id && (
          <p>
            <span className="font-medium">Channel:</span> {binding.channel_id}
          </p>
        )}
        {binding.account_id && (
          <p>
            <span className="font-medium">Account:</span> {binding.account_id}
          </p>
        )}
        {binding.peer_id && (
          <p>
            <span className="font-medium">Peer:</span> {binding.peer_id}
          </p>
        )}
      </div>

      <div className="flex items-center justify-between mt-3 pt-2 border-t border-slate-100 dark:border-slate-700">
        <span className="text-2xs text-slate-400">
          Priority: {binding.priority} | Specificity: {binding.specificity_score ?? 0}
        </span>
        <button
          type="button"
          onClick={() => {
            onDelete(binding.id);
          }}
          className="text-xs text-slate-400 hover:text-red-500 transition-colors"
        >
          Delete
        </button>
      </div>
    </div>
  );
});
BindingCard.displayName = 'BindingCard';

// ============================================================================
// Dashboard Bindings Component
// ============================================================================

export const DashboardBindings: FC = memo(() => {
  const { t } = useTranslation();

  const bindings = useBindings();
  const isLoading = useBindingLoading();
  const listBindings = useListBindings();
  const toggleBinding = useToggleBinding();
  const deleteBinding = useDeleteBinding();

  const definitions = useDefinitions();
  const listDefinitions = useListDefinitions();

  const [search, setSearch] = useState('');

  useEffect(() => {
    void listBindings();
    void listDefinitions();
  }, [listBindings, listDefinitions]);

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

  const handleToggle = useCallback(
    async (id: string, enabled: boolean) => {
      try {
        await toggleBinding(id, enabled);
      } catch {
        // Error handled by store
      }
    },
    [toggleBinding]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteBinding(id);
      } catch {
        // Error handled by store
      }
    },
    [deleteBinding]
  );

  const handleRefresh = useCallback(() => {
    void listBindings();
  }, [listBindings]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-white">
            {t('tenant.dashboard.bindings.title', 'Bindings')}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t('tenant.dashboard.bindings.subtitle', 'Route channels to specific agents')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleRefresh}
            disabled={isLoading}
            className="inline-flex items-center gap-2 px-3 py-1.5 text-sm text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition-colors"
          >
            <RefreshCw
              size={14}
              className={isLoading ? 'animate-spin motion-reduce:animate-none' : ''}
            />
            {t('common.refresh', 'Refresh')}
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-white text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors"
          >
            <Plus size={16} />
            {t('tenant.dashboard.bindings.addBinding', 'Add Binding')}
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
        <input
          type="text"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
          }}
          placeholder={t('tenant.dashboard.bindings.searchPlaceholder', 'Search bindings...')}
          aria-label={t('tenant.dashboard.bindings.searchPlaceholder', 'Search bindings...')}
          className="w-full pl-9 pr-3 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-primary/30 focus:border-primary outline-none"
        />
      </div>

      {/* Stats Summary */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('tenant.dashboard.bindings.totalBindings', 'Total Bindings')}
          </p>
          <p className="mt-1 text-xl font-bold text-slate-900 dark:text-white">{bindings.length}</p>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('tenant.dashboard.bindings.enabledBindings', 'Enabled')}
          </p>
          <p className="mt-1 text-xl font-bold text-green-600 dark:text-green-400">
            {bindings.filter((b) => b.enabled).length}
          </p>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('tenant.dashboard.bindings.agents', 'Agents')}
          </p>
          <p className="mt-1 text-xl font-bold text-slate-900 dark:text-white">
            {new Set(bindings.map((b) => b.agent_id)).size}
          </p>
        </div>
      </div>

      {/* Bindings Grid */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin motion-reduce:animate-none" />
        </div>
      ) : filteredBindings.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-slate-500 dark:text-slate-400">
          <Route size={48} className="mb-4 text-slate-300 dark:text-slate-600" />
          <p className="text-lg font-medium">
            {t('tenant.dashboard.bindings.noBindings', 'No bindings found')}
          </p>
          <p className="text-sm mt-1">
            {search
              ? t('tenant.dashboard.bindings.noResults', 'Try a different search term')
              : t(
                  'tenant.dashboard.bindings.emptyHint',
                  'Create bindings to route channels to agents'
                )}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredBindings.map((binding) => (
            <BindingCard
              key={binding.id}
              binding={binding}
              onToggle={handleToggle}
              onDelete={handleDelete}
              agentName={defNameMap.get(binding.agent_id) ?? binding.agent_id}
            />
          ))}
        </div>
      )}
    </div>
  );
});
DashboardBindings.displayName = 'DashboardBindings';

export default DashboardBindings;
