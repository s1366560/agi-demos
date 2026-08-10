import { useEffect, useMemo, useState, type FormEvent } from 'react';

import { useI18n } from '../../i18n';
import { TenantAdminRouteState } from '../tenant-admin/TenantAdminRouteState';
import type {
  BackendStore,
  BackendStorePlane,
  BackendStoreTestResult,
} from './backendStoresClient';
import type { BackendStoresController, BackendStoresViewModel } from './backendStoresController';

type StoreForm = Readonly<{
  name: string;
  engineType: string;
  connectionConfig: string;
  indexConfig: string;
}>;

const EMPTY_JSON = '{}';

export function BackendStoresPage({
  model,
  controller,
  onRetry,
}: Readonly<{
  model: BackendStoresViewModel;
  controller: BackendStoresController | null;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const [plane, setPlane] = useState<BackendStorePlane>('graph');
  const planeData = plane === 'graph' ? model.graph : model.retrieval;
  const [form, setForm] = useState<StoreForm>(() => emptyForm('graph'));
  const [editing, setEditing] = useState<BackendStore | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const canMutate = controller !== null && model.allowedActions.includes('create');
  const defaultEngine = planeData.types[0]?.type ?? defaultEngineType(plane);

  useEffect(() => {
    setEditing(null);
    setConfirmDelete(null);
    setMessage(null);
    setForm(emptyForm(plane, defaultEngine));
  }, [plane, defaultEngine]);

  const terminal = !['ready', 'degraded', 'empty', 'stale'].includes(model.state);
  if (terminal) {
    return (
      <TenantAdminRouteState
        state={model.state}
        reasonCode={model.reasonCode}
        retryVisible={model.retryVisible}
        onRetry={onRetry}
      />
    );
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!controller) return;
    setMessage(null);
    try {
      const connectionConfig = parseObject(form.connectionConfig);
      const indexConfig = parseObject(form.indexConfig);
      if (editing) {
        await controller.update(plane, editing.id, {
          name: form.name.trim(),
          connectionConfig,
          indexConfig,
        });
      } else {
        await controller.create(plane, {
          name: form.name.trim(),
          engineType: form.engineType,
          connectionConfig,
          indexConfig,
        });
      }
      setEditing(null);
      setForm(emptyForm(plane, defaultEngine));
      setMessage(t(editing ? 'backendStores.updated' : 'backendStores.created'));
    } catch (error) {
      setMessage(errorMessage(error));
    }
  };

  const testDraft = async () => {
    if (!controller) return;
    setMessage(null);
    try {
      const result = await controller.testDraft(plane, {
        engineType: form.engineType,
        connectionConfig: parseObject(form.connectionConfig),
      });
      setMessage(testMessage(result, t));
    } catch (error) {
      setMessage(errorMessage(error));
    }
  };

  return (
    <section data-route-id="backend-stores" data-state={model.state} data-plane={plane}>
      <header>
        <div>
          <h1>{t('backendStores.title')}</h1>
          <p>{t('backendStores.subtitle')}</p>
        </div>
        <button type="button" onClick={onRetry} disabled={Boolean(model.busyAction)}>
          {t('common.refresh')}
        </button>
      </header>

      {model.reasonCode ? (
        <p role="status">{t(`backendStores.reason.${model.reasonCode}`)}</p>
      ) : null}
      {message ? <p role="status">{message}</p> : null}

      <nav aria-label={t('backendStores.planeLabel')}>
        {(['graph', 'retrieval'] as const).map((candidate) => (
          <button
            key={candidate}
            type="button"
            aria-pressed={plane === candidate}
            onClick={() => setPlane(candidate)}
          >
            {t(`backendStores.plane.${candidate}`)}
          </button>
        ))}
      </nav>

      {canMutate ? (
        <form onSubmit={(event) => void submit(event)}>
          <h2>{t(editing ? 'backendStores.editTitle' : 'backendStores.createTitle')}</h2>
          <label>
            <span>{t('backendStores.name')}</span>
            <input
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              required
            />
          </label>
          <label>
            <span>{t('backendStores.engine')}</span>
            <select
              value={form.engineType}
              disabled={editing !== null}
              onChange={(event) => setForm({ ...form, engineType: event.target.value })}
            >
              {(planeData.types.length > 0
                ? planeData.types
                : [{ type: defaultEngine, displayName: defaultEngine }]
              ).map((type) => (
                <option key={type.type} value={type.type}>
                  {type.displayName}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>{t('backendStores.connectionConfig')}</span>
            <textarea
              value={form.connectionConfig}
              onChange={(event) => setForm({ ...form, connectionConfig: event.target.value })}
              rows={7}
              spellCheck={false}
            />
          </label>
          <label>
            <span>{t('backendStores.indexConfig')}</span>
            <textarea
              value={form.indexConfig}
              onChange={(event) => setForm({ ...form, indexConfig: event.target.value })}
              rows={5}
              spellCheck={false}
            />
          </label>
          <div>
            <button
              type="button"
              onClick={() => void testDraft()}
              disabled={Boolean(model.busyAction)}
            >
              {t('backendStores.testDraft')}
            </button>
            <button type="submit" disabled={!form.name.trim() || Boolean(model.busyAction)}>
              {t(editing ? 'common.save' : 'backendStores.create')}
            </button>
            {editing ? (
              <button
                type="button"
                onClick={() => {
                  setEditing(null);
                  setForm(emptyForm(plane, defaultEngine));
                }}
              >
                {t('common.cancel')}
              </button>
            ) : null}
          </div>
        </form>
      ) : null}

      <StoreList
        stores={planeData.stores}
        plane={plane}
        busy={Boolean(model.busyAction)}
        controller={controller}
        confirmDelete={confirmDelete}
        onConfirmDelete={setConfirmDelete}
        onEdit={(store) => {
          setEditing(store);
          setForm(formForStore(store));
        }}
        onMessage={setMessage}
      />
    </section>
  );
}

function StoreList({
  stores,
  plane,
  busy,
  controller,
  confirmDelete,
  onConfirmDelete,
  onEdit,
  onMessage,
}: Readonly<{
  stores: readonly BackendStore[];
  plane: BackendStorePlane;
  busy: boolean;
  controller: BackendStoresController | null;
  confirmDelete: string | null;
  onConfirmDelete: (storeId: string | null) => void;
  onEdit: (store: BackendStore) => void;
  onMessage: (message: string | null) => void;
}>) {
  const { t } = useI18n();
  const mutable = useMemo(
    () => new Set(controller ? ['update', 'delete', 'test'] : []),
    [controller],
  );
  if (stores.length === 0) return <p>{t('backendStores.empty')}</p>;
  return (
    <ul>
      {stores.map((store) => (
        <li key={store.id}>
          <article>
            <header>
              <div>
                <h2>{store.name}</h2>
                <p>
                  {store.engineType} · {store.status}
                </p>
              </div>
              <code>{store.source}</code>
            </header>
            {store.detectedVersion ? (
              <p>
                {t('backendStores.version')}: {store.detectedVersion}
              </p>
            ) : null}
            {!store.readonly && controller ? (
              <div>
                {mutable.has('test') ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void controller
                        .testStore(plane, store.id)
                        .then((result) => onMessage(testMessage(result, t)))
                        .catch((error) => onMessage(errorMessage(error)))
                    }
                  >
                    {t('backendStores.test')}
                  </button>
                ) : null}
                {mutable.has('update') ? (
                  <button type="button" disabled={busy} onClick={() => onEdit(store)}>
                    {t('common.edit')}
                  </button>
                ) : null}
                {mutable.has('delete') ? (
                  confirmDelete === store.id ? (
                    <span>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          void controller
                            .remove(plane, store.id)
                            .then(() => onConfirmDelete(null))
                            .catch((error) => onMessage(errorMessage(error)))
                        }
                      >
                        {t('common.delete')}
                      </button>
                      <button type="button" onClick={() => onConfirmDelete(null)}>
                        {t('common.cancel')}
                      </button>
                    </span>
                  ) : (
                    <button type="button" disabled={busy} onClick={() => onConfirmDelete(store.id)}>
                      {t('common.delete')}
                    </button>
                  )
                ) : null}
              </div>
            ) : null}
          </article>
        </li>
      ))}
    </ul>
  );
}

function emptyForm(plane: BackendStorePlane, engineType = defaultEngineType(plane)): StoreForm {
  return Object.freeze({
    name: '',
    engineType,
    connectionConfig: EMPTY_JSON,
    indexConfig: EMPTY_JSON,
  });
}

function formForStore(store: BackendStore): StoreForm {
  return Object.freeze({
    name: store.name,
    engineType: store.engineType,
    connectionConfig: JSON.stringify(store.connectionConfig, null, 2),
    indexConfig: JSON.stringify(store.indexConfig, null, 2),
  });
}

function defaultEngineType(plane: BackendStorePlane): string {
  return plane === 'graph' ? 'neo4j' : 'memstack_pgvector';
}

function parseObject(value: string): Readonly<Record<string, unknown>> {
  const parsed = JSON.parse(value.trim() || EMPTY_JSON) as unknown;
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error('backend_store_config_object_required');
  }
  return parsed as Record<string, unknown>;
}

function testMessage(result: BackendStoreTestResult, t: (key: string) => string): string {
  return result.success
    ? `${t('backendStores.testSucceeded')}${result.version ? ` ${result.version}` : ''}`
    : (result.error ?? t('backendStores.testFailed'));
}

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return 'backend_stores_request_failed';
}
