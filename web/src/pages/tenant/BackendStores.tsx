import React, { useCallback, useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import {
  CheckCircle2,
  Database,
  FlaskConical,
  Loader2,
  Network,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Trash2,
  XCircle,
} from 'lucide-react';

import { useTenantStore } from '@/stores/tenant';

import { graphStoreAPI, retrievalStoreAPI } from '@/services/api';

import { confirmAction } from '@/utils/confirmAction';

import { AppModal } from '@/components/common';
import { LazyEmpty } from '@/components/ui/lazyAntd';

import type {
  BackendStore,
  BackendStoreCreate,
  BackendStoreTestRequest,
  BackendStoreTypeInfo,
  BackendStoreUpdate,
} from '@/types/memory';

type StorePlane = 'graph' | 'retrieval';
type MessageKind = 'success' | 'error';

interface StoreFormState {
  name: string;
  engine_type: string;
  connection_config_text: string;
  index_config_text: string;
}

interface StoreMessage {
  kind: MessageKind;
  text: string;
}

const DEFAULT_JSON_TEXT = '{}';

const defaultEngineType = (plane: StorePlane): string =>
  plane === 'graph' ? 'neo4j' : 'memstack_pgvector';

const defaultFormState = (plane: StorePlane, engineType?: string): StoreFormState => ({
  name: '',
  engine_type: engineType ?? defaultEngineType(plane),
  connection_config_text: DEFAULT_JSON_TEXT,
  index_config_text: DEFAULT_JSON_TEXT,
});

const apiForPlane = (plane: StorePlane) => (plane === 'graph' ? graphStoreAPI : retrievalStoreAPI);

const formatJson = (value: Record<string, unknown> | undefined): string =>
  JSON.stringify(value ?? {}, null, 2);

const parseJsonObject = (text: string): Record<string, unknown> => {
  const trimmed = text.trim();
  if (!trimmed) return {};
  const parsed = JSON.parse(trimmed) as unknown;
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error('not-object');
  }
  return parsed as Record<string, unknown>;
};

const containsRedactedPlaceholder = (value: unknown): boolean => {
  if (value === '***') return true;
  if (Array.isArray(value)) return value.some(containsRedactedPlaceholder);
  if (value && typeof value === 'object') {
    return Object.values(value as Record<string, unknown>).some(containsRedactedPlaceholder);
  }
  return false;
};

const getErrorMessage = (error: unknown, fallback: string): string => {
  if (error instanceof Error) return error.message;
  if (error && typeof error === 'object' && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: unknown; error?: unknown } } })
      .response;
    const detail = response?.data?.detail ?? response?.data?.error;
    if (typeof detail === 'string') return detail;
  }
  return fallback;
};

export const BackendStores: React.FC = () => {
  const { t } = useTranslation();
  const { tenantId: routeTenantId } = useParams<{ tenantId?: string }>();
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const tenantId = routeTenantId ?? currentTenant?.id ?? null;
  const [activePlane, setActivePlane] = useState<StorePlane>('graph');
  const [graphStores, setGraphStores] = useState<BackendStore[]>([]);
  const [retrievalStores, setRetrievalStores] = useState<BackendStore[]>([]);
  const [graphTypes, setGraphTypes] = useState<BackendStoreTypeInfo[]>([]);
  const [retrievalTypes, setRetrievalTypes] = useState<BackendStoreTypeInfo[]>([]);
  const [createForm, setCreateForm] = useState<StoreFormState>(defaultFormState('graph'));
  const [editStore, setEditStore] = useState<BackendStore | null>(null);
  const [editForm, setEditForm] = useState<StoreFormState>(defaultFormState('graph'));
  const [message, setMessage] = useState<StoreMessage | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isTestingDraft, setIsTestingDraft] = useState(false);
  const [testingStoreId, setTestingStoreId] = useState<string | null>(null);

  const currentStores = activePlane === 'graph' ? graphStores : retrievalStores;
  const currentTypes = activePlane === 'graph' ? graphTypes : retrievalTypes;
  const planeApi = apiForPlane(activePlane);

  const loadStores = useCallback(
    async (plane: StorePlane) => {
      if (!tenantId) return;
      setIsLoading(true);
      setMessage(null);
      try {
        const api = apiForPlane(plane);
        const [stores, types] = await Promise.all([api.list(tenantId), api.types()]);
        if (plane === 'graph') {
          setGraphStores(stores);
          setGraphTypes(types);
        } else {
          setRetrievalStores(stores);
          setRetrievalTypes(types);
        }
        setLoadFailed(false);
      } catch (loadError) {
        setLoadFailed(true);
        setMessage({
          kind: 'error',
          text: getErrorMessage(
            loadError,
            t('tenant.backendStores.loadFailed', {
              defaultValue: 'Failed to load backend stores.',
            })
          ),
        });
      } finally {
        setIsLoading(false);
      }
    },
    [tenantId, t]
  );

  useEffect(() => {
    void loadStores(activePlane);
  }, [activePlane, loadStores]);

  useEffect(() => {
    setCreateForm(defaultFormState(activePlane, currentTypes[0]?.type));
  }, [activePlane, currentTypes]);

  const replaceStore = (store: BackendStore) => {
    if (activePlane === 'graph') {
      setGraphStores((stores) => stores.map((item) => (item.id === store.id ? store : item)));
    } else {
      setRetrievalStores((stores) => stores.map((item) => (item.id === store.id ? store : item)));
    }
  };

  const removeStore = (storeId: string) => {
    if (activePlane === 'graph') {
      setGraphStores((stores) => stores.filter((store) => store.id !== storeId));
    } else {
      setRetrievalStores((stores) => stores.filter((store) => store.id !== storeId));
    }
  };

  const appendStore = (store: BackendStore) => {
    if (activePlane === 'graph') {
      setGraphStores((stores) => [...stores, store]);
    } else {
      setRetrievalStores((stores) => [...stores, store]);
    }
  };

  const parseFormConfig = (form: StoreFormState) => {
    try {
      const connectionConfig = parseJsonObject(form.connection_config_text);
      const indexConfig = parseJsonObject(form.index_config_text);
      if (containsRedactedPlaceholder(connectionConfig)) {
        setMessage({
          kind: 'error',
          text: t('tenant.backendStores.replaceMaskedSecrets', {
            defaultValue: 'Replace masked secret placeholders before saving connection config.',
          }),
        });
        return null;
      }
      return { connectionConfig, indexConfig };
    } catch {
      setMessage({
        kind: 'error',
        text: t('tenant.backendStores.invalidJson', {
          defaultValue: 'Configuration must be a JSON object.',
        }),
      });
      return null;
    }
  };

  const handleCreate = async () => {
    if (!tenantId) return;
    const config = parseFormConfig(createForm);
    if (!config) return;
    setIsSaving(true);
    setMessage(null);
    try {
      const payload: BackendStoreCreate = {
        name: createForm.name.trim(),
        engine_type: createForm.engine_type,
        connection_config: config.connectionConfig,
        index_config: config.indexConfig,
      };
      const created = await planeApi.create(tenantId, payload);
      appendStore(created);
      setCreateForm(defaultFormState(activePlane, currentTypes[0]?.type));
      setMessage({
        kind: 'success',
        text: t('tenant.backendStores.created', { defaultValue: 'Store created.' }),
      });
    } catch (createError) {
      setMessage({
        kind: 'error',
        text: getErrorMessage(
          createError,
          t('tenant.backendStores.createFailed', { defaultValue: 'Failed to create store.' })
        ),
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleTestDraft = async () => {
    if (!tenantId) return;
    const config = parseFormConfig(createForm);
    if (!config) return;
    const payload: BackendStoreTestRequest = {
      engine_type: createForm.engine_type,
      connection_config: config.connectionConfig,
    };
    setIsTestingDraft(true);
    setMessage(null);
    try {
      const result = await planeApi.testRaw(tenantId, payload);
      setMessage({
        kind: result.success ? 'success' : 'error',
        text: result.success
          ? t('tenant.backendStores.testSucceeded', {
              defaultValue: 'Connection test succeeded. Version: {{version}}',
              version: result.version ?? 'unknown',
            })
          : (result.error ??
            t('tenant.backendStores.testFailed', { defaultValue: 'Connection test failed.' })),
      });
    } catch (testError) {
      setMessage({
        kind: 'error',
        text: getErrorMessage(
          testError,
          t('tenant.backendStores.testFailed', { defaultValue: 'Connection test failed.' })
        ),
      });
    } finally {
      setIsTestingDraft(false);
    }
  };

  const handleTestSaved = async (store: BackendStore) => {
    if (!tenantId) return;
    setTestingStoreId(store.id);
    setMessage(null);
    try {
      const result = await planeApi.testById(tenantId, store.id);
      setMessage({
        kind: result.success ? 'success' : 'error',
        text: result.success
          ? t('tenant.backendStores.testSucceeded', {
              defaultValue: 'Connection test succeeded. Version: {{version}}',
              version: result.version ?? 'unknown',
            })
          : (result.error ??
            t('tenant.backendStores.testFailed', { defaultValue: 'Connection test failed.' })),
      });
    } catch (testError) {
      setMessage({
        kind: 'error',
        text: getErrorMessage(
          testError,
          t('tenant.backendStores.testFailed', { defaultValue: 'Connection test failed.' })
        ),
      });
    } finally {
      setTestingStoreId(null);
    }
  };

  const openEdit = (store: BackendStore) => {
    setEditStore(store);
    setEditForm({
      name: store.name,
      engine_type: store.engine_type,
      connection_config_text: formatJson(store.connection_config),
      index_config_text: formatJson(store.index_config),
    });
    setMessage(null);
  };

  const handleSaveEdit = async () => {
    if (!tenantId || !editStore) return;

    // Validate JSON up front so users see the friendly message, not a raw parse error
    let indexConfig: Record<string, unknown>;
    let connectionConfig: Record<string, unknown> | undefined;
    try {
      indexConfig = parseJsonObject(editForm.index_config_text);
      const originalConnectionText = formatJson(editStore.connection_config);
      if (editForm.connection_config_text.trim() !== originalConnectionText.trim()) {
        connectionConfig = parseJsonObject(editForm.connection_config_text);
      }
    } catch {
      setMessage({
        kind: 'error',
        text: t('tenant.backendStores.invalidJson', {
          defaultValue: 'Configuration must be a JSON object.',
        }),
      });
      return;
    }

    if (connectionConfig && containsRedactedPlaceholder(connectionConfig)) {
      setMessage({
        kind: 'error',
        text: t('tenant.backendStores.replaceMaskedSecrets', {
          defaultValue: 'Replace masked secret placeholders before saving connection config.',
        }),
      });
      return;
    }

    setIsSaving(true);
    setMessage(null);
    try {
      const payload: BackendStoreUpdate = {
        name: editForm.name.trim(),
        index_config: indexConfig,
      };
      if (connectionConfig) {
        payload.connection_config = connectionConfig;
      }
      const updated = await planeApi.update(tenantId, editStore.id, payload);
      replaceStore(updated);
      setEditStore(null);
      setMessage({
        kind: 'success',
        text: t('tenant.backendStores.updated', { defaultValue: 'Store updated.' }),
      });
    } catch (saveError) {
      setMessage({
        kind: 'error',
        text: getErrorMessage(
          saveError,
          t('tenant.backendStores.updateFailed', { defaultValue: 'Failed to update store.' })
        ),
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async (store: BackendStore) => {
    if (!tenantId || store.readonly) return;
    if (
      !(await confirmAction({
        title: t('tenant.backendStores.deleteConfirm', {
          name: store.name,
          defaultValue: 'Delete backend store "{{name}}"?',
        }),
        danger: true,
      }))
    ) {
      return;
    }
    setMessage(null);
    try {
      await planeApi.delete(tenantId, store.id);
      removeStore(store.id);
      setMessage({
        kind: 'success',
        text: t('tenant.backendStores.deleted', { defaultValue: 'Store deleted.' }),
      });
    } catch (deleteError) {
      setMessage({
        kind: 'error',
        text: getErrorMessage(
          deleteError,
          t('tenant.backendStores.deleteFailed', {
            defaultValue: 'Failed to delete store.',
          })
        ),
      });
    }
  };

  if (!tenantId) {
    return (
      <div className="flex items-center justify-center p-16">
        <LazyEmpty description={t('common.noTenant')} />
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-full flex-col gap-8 pb-10">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white">
            {t('tenant.backendStores.title', { defaultValue: 'Backend stores' })}
          </h1>
          <p className="text-sm text-slate-500">
            {t('tenant.backendStores.subtitle', {
              defaultValue: 'Manage graph and retrieval backends for project bindings.',
            })}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => {
              void loadStores(activePlane);
            }}
            disabled={isLoading}
            aria-label={t('common.refresh')}
            title={t('common.refresh')}
            className="flex h-10 items-center gap-2 rounded-lg border border-slate-300 px-3 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            <RefreshCw size={15} />
          </button>
          <div className="inline-flex rounded-lg border border-slate-200 bg-white p-1 shadow-sm dark:border-slate-800 dark:bg-surface-dark">
            <button
              type="button"
              aria-pressed={activePlane === 'graph'}
              onClick={() => {
                setActivePlane('graph');
              }}
              className={`flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
                activePlane === 'graph'
                  ? 'bg-primary text-white'
                  : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
              }`}
            >
              <Network size={15} />
              {t('tenant.backendStores.graph', { defaultValue: 'Graph' })}
            </button>
            <button
              type="button"
              aria-pressed={activePlane === 'retrieval'}
              onClick={() => {
                setActivePlane('retrieval');
              }}
              className={`flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
                activePlane === 'retrieval'
                  ? 'bg-primary text-white'
                  : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
              }`}
            >
              <Database size={15} />
              {t('tenant.backendStores.retrieval', { defaultValue: 'Retrieval' })}
            </button>
          </div>
        </div>
      </div>

      {message && (
        <div
          role={message.kind === 'error' ? 'alert' : 'status'}
          className={`flex items-center gap-2 rounded-lg border px-4 py-3 text-sm ${
            message.kind === 'success'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-300'
              : 'border-red-200 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-300'
          }`}
        >
          {message.kind === 'success' ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
          {message.text}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(320px,420px)_1fr]">
        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-surface-dark">
          <div className="mb-5 flex items-center gap-3">
            <div className="rounded-lg bg-primary/10 p-2 text-primary">
              <Plus size={16} />
            </div>
            <h2 className="text-lg font-bold text-slate-900 dark:text-white">
              {t('tenant.backendStores.createTitle', { defaultValue: 'Create store' })}
            </h2>
          </div>
          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              void handleCreate();
            }}
          >
            <label className="flex flex-col gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
              {t('common.forms.name')}
              <input
                value={createForm.name}
                onChange={(event) => {
                  setCreateForm({ ...createForm, name: event.target.value });
                }}
                className="rounded-lg border border-slate-300 bg-slate-50 px-4 py-2.5 text-slate-900 outline-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary dark:border-slate-700 dark:bg-slate-900 dark:text-white"
              />
            </label>
            <label className="flex flex-col gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
              {t('tenant.backendStores.engineType', { defaultValue: 'Engine type' })}
              <select
                value={createForm.engine_type}
                onChange={(event) => {
                  setCreateForm({ ...createForm, engine_type: event.target.value });
                }}
                className="rounded-lg border border-slate-300 bg-slate-50 px-4 py-2.5 text-slate-900 outline-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary dark:border-slate-700 dark:bg-slate-900 dark:text-white"
              >
                {currentTypes.map((typeInfo) => (
                  <option key={typeInfo.type} value={typeInfo.type}>
                    {typeInfo.display_name}
                  </option>
                ))}
                {currentTypes.length === 0 && (
                  <option value={defaultEngineType(activePlane)}>
                    {defaultEngineType(activePlane)}
                  </option>
                )}
              </select>
            </label>
            <label className="flex flex-col gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
              {t('tenant.backendStores.connectionConfig', {
                defaultValue: 'Connection config',
              })}
              <textarea
                rows={8}
                spellCheck={false}
                value={createForm.connection_config_text}
                onChange={(event) => {
                  setCreateForm({
                    ...createForm,
                    connection_config_text: event.target.value,
                  });
                }}
                className="font-mono text-xs rounded-lg border border-slate-300 bg-slate-50 px-4 py-3 text-slate-900 outline-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary dark:border-slate-700 dark:bg-slate-900 dark:text-white"
              />
            </label>
            <label className="flex flex-col gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
              {t('tenant.backendStores.indexConfig', { defaultValue: 'Index config' })}
              <textarea
                rows={5}
                spellCheck={false}
                value={createForm.index_config_text}
                onChange={(event) => {
                  setCreateForm({ ...createForm, index_config_text: event.target.value });
                }}
                className="font-mono text-xs rounded-lg border border-slate-300 bg-slate-50 px-4 py-3 text-slate-900 outline-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary dark:border-slate-700 dark:bg-slate-900 dark:text-white"
              />
            </label>
            <div className="flex flex-wrap justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => {
                  void handleTestDraft();
                }}
                disabled={isTestingDraft || isSaving}
                className="flex items-center gap-2 rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                {isTestingDraft ? (
                  <Loader2 size={15} className="animate-spin motion-reduce:animate-none" />
                ) : (
                  <FlaskConical size={15} />
                )}
                {t('tenant.backendStores.testConnection', {
                  defaultValue: 'Test connection',
                })}
              </button>
              <button
                type="submit"
                disabled={isSaving || !createForm.name.trim()}
                className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-white shadow-lg shadow-primary/20 transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isSaving ? (
                  <Loader2 size={15} className="animate-spin motion-reduce:animate-none" />
                ) : (
                  <Plus size={15} />
                )}
                {t('common.create')}
              </button>
            </div>
          </form>
        </section>

        <section className="flex min-w-0 flex-col gap-4">
          {isLoading && (
            <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-slate-500 dark:border-slate-800 dark:bg-surface-dark">
              <Loader2 className="mx-auto mb-3 animate-spin motion-reduce:animate-none" size={22} />
              {t('tenant.projects.loading')}
            </div>
          )}

          {!isLoading &&
            currentStores.map((store) => (
              <article
                key={store.id}
                className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-surface-dark"
              >
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="truncate text-base font-bold text-slate-900 dark:text-white">
                        {store.name}
                      </h3>
                      {store.readonly && (
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-500 dark:bg-slate-800 dark:text-slate-300">
                          {t('tenant.backendStores.readonly', { defaultValue: 'readonly' })}
                        </span>
                      )}
                      <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">
                        {store.engine_type}
                      </span>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
                      <span>{t(`tenant.backendStores.status.${store.status}`, store.status)}</span>
                      <span>
                        {store.health_status
                          ? t(
                              `tenant.backendStores.healthStatus.${store.health_status}`,
                              store.health_status
                            )
                          : '-'}
                      </span>
                      <span>{store.detected_version ?? '-'}</span>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        void handleTestSaved(store);
                      }}
                      disabled={testingStoreId === store.id}
                      className="flex h-9 items-center gap-2 rounded-lg border border-slate-300 px-3 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                    >
                      {testingStoreId === store.id ? (
                        <Loader2 size={15} className="animate-spin motion-reduce:animate-none" />
                      ) : (
                        <FlaskConical size={15} />
                      )}
                      {t('tenant.backendStores.test', { defaultValue: 'Test' })}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        openEdit(store);
                      }}
                      disabled={store.readonly}
                      className="flex h-9 items-center gap-2 rounded-lg border border-slate-300 px-3 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                    >
                      <Pencil size={15} />
                      {t('common.edit')}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        void handleDelete(store);
                      }}
                      disabled={store.readonly}
                      className="flex h-9 items-center gap-2 rounded-lg border border-red-200 px-3 text-sm font-medium text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-red-900/60 dark:text-red-300 dark:hover:bg-red-900/20"
                    >
                      <Trash2 size={15} />
                      {t('common.delete')}
                    </button>
                  </div>
                </div>
                <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase text-slate-400">
                      {t('tenant.backendStores.connectionConfig', {
                        defaultValue: 'Connection config',
                      })}
                    </div>
                    <pre className="max-h-48 overflow-auto rounded-lg bg-slate-50 p-3 text-xs text-slate-700 dark:bg-slate-900 dark:text-slate-300">
                      {formatJson(store.connection_config)}
                    </pre>
                  </div>
                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase text-slate-400">
                      {t('tenant.backendStores.indexConfig', { defaultValue: 'Index config' })}
                    </div>
                    <pre className="max-h-48 overflow-auto rounded-lg bg-slate-50 p-3 text-xs text-slate-700 dark:bg-slate-900 dark:text-slate-300">
                      {formatJson(store.index_config)}
                    </pre>
                  </div>
                </div>
              </article>
            ))}

          {!isLoading && loadFailed && currentStores.length === 0 && (
            <div
              role="alert"
              className="flex flex-col items-center gap-3 rounded-xl border border-red-200 bg-red-50 p-8 text-center dark:border-red-800 dark:bg-red-900/20"
            >
              <p className="text-sm text-red-700 dark:text-red-300">
                {t('tenant.backendStores.loadFailed', {
                  defaultValue: 'Failed to load backend stores.',
                })}
              </p>
              <button
                type="button"
                onClick={() => {
                  void loadStores(activePlane);
                }}
                className="rounded-lg border border-red-300 px-4 py-2 text-sm font-medium text-red-700 transition-colors hover:bg-red-100 dark:border-red-700 dark:text-red-300 dark:hover:bg-red-900/40"
              >
                {t('common.retry')}
              </button>
            </div>
          )}

          {!isLoading && !loadFailed && currentStores.length === 0 && (
            <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-slate-500 dark:border-slate-800 dark:bg-surface-dark">
              {t('tenant.backendStores.empty', { defaultValue: 'No backend stores found.' })}
            </div>
          )}
        </section>
      </div>

      <AppModal
        open={!!editStore}
        onClose={() => {
          setEditStore(null);
        }}
        title={t('tenant.backendStores.editTitle', { defaultValue: 'Edit store' })}
        description={editStore?.engine_type}
        size="lg"
        isDirty={() =>
          editStore !== null &&
          (editForm.name !== editStore.name ||
            editForm.connection_config_text !== formatJson(editStore.connection_config) ||
            editForm.index_config_text !== formatJson(editStore.index_config))
        }
        footer={
          <>
            <button
              type="button"
              onClick={() => {
                setEditStore(null);
              }}
              className="rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              {t('common.cancel')}
            </button>
            <button
              type="button"
              onClick={() => {
                void handleSaveEdit();
              }}
              disabled={isSaving || !editForm.name.trim()}
              className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-white shadow-lg shadow-primary/20 hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isSaving ? (
                <Loader2 size={15} className="animate-spin motion-reduce:animate-none" />
              ) : (
                <Save size={15} />
              )}
              {t('common.save')}
            </button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
            {t('common.forms.name')}
            <input
              value={editForm.name}
              onChange={(event) => {
                setEditForm({ ...editForm, name: event.target.value });
              }}
              className="rounded-lg border border-slate-300 bg-slate-50 px-4 py-2.5 text-slate-900 outline-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary dark:border-slate-700 dark:bg-slate-900 dark:text-white"
            />
          </label>
          <label className="flex flex-col gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
            {t('tenant.backendStores.connectionConfig', {
              defaultValue: 'Connection config',
            })}
            <textarea
              rows={9}
              spellCheck={false}
              value={editForm.connection_config_text}
              onChange={(event) => {
                setEditForm({
                  ...editForm,
                  connection_config_text: event.target.value,
                });
              }}
              className="font-mono text-xs rounded-lg border border-slate-300 bg-slate-50 px-4 py-3 text-slate-900 outline-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary dark:border-slate-700 dark:bg-slate-900 dark:text-white"
            />
          </label>
          <label className="flex flex-col gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
            {t('tenant.backendStores.indexConfig', { defaultValue: 'Index config' })}
            <textarea
              rows={6}
              spellCheck={false}
              value={editForm.index_config_text}
              onChange={(event) => {
                setEditForm({ ...editForm, index_config_text: event.target.value });
              }}
              className="font-mono text-xs rounded-lg border border-slate-300 bg-slate-50 px-4 py-3 text-slate-900 outline-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary dark:border-slate-700 dark:bg-slate-900 dark:text-white"
            />
          </label>
        </div>
      </AppModal>
    </div>
  );
};
