import React, { useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Database, Network } from 'lucide-react';

import { graphStoreAPI, retrievalStoreAPI } from '@/services/api';

import type { BackendStore } from '@/types/memory';

interface BackendStoreSelectorsProps {
  tenantId?: string | null | undefined;
  graphStoreId?: string | null | undefined;
  retrievalStoreId?: string | null | undefined;
  disabled?: boolean | undefined;
  onChange: (patch: {
    graph_store_id?: string | null | undefined;
    retrieval_store_id?: string | null | undefined;
  }) => void;
}

const envStoreLabel = (store: BackendStore | undefined, fallback: string): string => {
  if (!store) return fallback;
  return `${store.name} (${store.engine_type})`;
};

export const BackendStoreSelectors: React.FC<BackendStoreSelectorsProps> = ({
  tenantId,
  graphStoreId,
  retrievalStoreId,
  disabled = false,
  onChange,
}) => {
  const { t } = useTranslation();
  const [graphStores, setGraphStores] = useState<BackendStore[]>([]);
  const [retrievalStores, setRetrievalStores] = useState<BackendStore[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;

    const loadStores = async () => {
      if (!tenantId) return;
      setIsLoading(true);
      setError(null);
      try {
        const [graphResult, retrievalResult] = await Promise.all([
          graphStoreAPI.list(tenantId),
          retrievalStoreAPI.list(tenantId),
        ]);
        if (!cancelled) {
          setGraphStores(graphResult);
          setRetrievalStores(retrievalResult);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(
            loadError instanceof Error
              ? loadError.message
              : t('tenant.backendStores.loadFailed', {
                  defaultValue: 'Failed to load backend stores.',
                })
          );
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    void loadStores();
    return () => {
      cancelled = true;
    };
  }, [tenantId, t, reloadToken]);

  const graphEnvStore = useMemo(
    () => graphStores.find((store) => store.source === 'env'),
    [graphStores]
  );
  const retrievalEnvStore = useMemo(
    () => retrievalStores.find((store) => store.source === 'env'),
    [retrievalStores]
  );
  const userGraphStores = useMemo(
    () => graphStores.filter((store) => store.source !== 'env'),
    [graphStores]
  );
  const userRetrievalStores = useMemo(
    () => retrievalStores.filter((store) => store.source !== 'env'),
    [retrievalStores]
  );
  const graphStoreLabel = t('tenant.backendStores.graphStore', { defaultValue: 'Graph store' });
  const retrievalStoreLabel = t('tenant.backendStores.retrievalStore', {
    defaultValue: 'Retrieval store',
  });

  return (
    <div className="bg-surface-light dark:bg-surface-dark border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm">
      <div className="flex items-center gap-3 mb-6">
        <div className="p-2 bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600 dark:text-emerald-400 rounded-lg">
          <Database size={16} />
        </div>
        <h2 className="text-lg font-bold text-slate-900 dark:text-white">
          {t('tenant.backendStores.projectBindings', { defaultValue: 'Backend bindings' })}
        </h2>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-4 flex items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-300"
        >
          <span>{error}</span>
          <button
            type="button"
            onClick={() => {
              setReloadToken((token) => token + 1);
            }}
            className="shrink-0 rounded-lg px-3 py-1.5 font-medium transition-colors hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:hover:bg-red-900/40"
          >
            {t('common.retry', { defaultValue: 'Retry' })}
          </button>
        </div>
      )}

      {isLoading && (
        <p className="mb-4 text-sm text-slate-500 dark:text-slate-400" role="status">
          {t('common.loading', { defaultValue: 'Loading…' })}
        </p>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div>
          <label
            htmlFor="project-graph-store-select"
            className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300"
          >
            <Network size={15} />
            {graphStoreLabel}
          </label>
          <select
            id="project-graph-store-select"
            aria-label={graphStoreLabel}
            value={graphStoreId ?? ''}
            disabled={disabled || isLoading || !tenantId}
            onChange={(event) => {
              onChange({ graph_store_id: event.target.value || null });
            }}
            className="w-full rounded-lg border border-slate-300 bg-slate-50 px-4 py-2.5 text-slate-900 outline-none transition-[color,background-color,border-color,box-shadow,opacity,transform] focus:border-primary focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
          >
            <option value="">
              {envStoreLabel(
                graphEnvStore,
                t('tenant.backendStores.environmentDefault', {
                  defaultValue: 'Environment default',
                })
              )}
            </option>
            {userGraphStores.map((store) => (
              <option key={store.id} value={store.id}>
                {store.name} ({store.engine_type})
              </option>
            ))}
          </select>
        </div>

        <div>
          <label
            htmlFor="project-retrieval-store-select"
            className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300"
          >
            <Database size={15} />
            {retrievalStoreLabel}
          </label>
          <select
            id="project-retrieval-store-select"
            aria-label={retrievalStoreLabel}
            value={retrievalStoreId ?? ''}
            disabled={disabled || isLoading || !tenantId}
            onChange={(event) => {
              onChange({ retrieval_store_id: event.target.value || null });
            }}
            className="w-full rounded-lg border border-slate-300 bg-slate-50 px-4 py-2.5 text-slate-900 outline-none transition-[color,background-color,border-color,box-shadow,opacity,transform] focus:border-primary focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
          >
            <option value="">
              {envStoreLabel(
                retrievalEnvStore,
                t('tenant.backendStores.environmentDefault', {
                  defaultValue: 'Environment default',
                })
              )}
            </option>
            {userRetrievalStores.map((store) => (
              <option key={store.id} value={store.id}>
                {store.name} ({store.engine_type})
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
};
