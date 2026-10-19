import { useCallback, useLayoutEffect, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { useCurrentWebPluginGenerationStateV2 } from '../../plugins/WebPluginGenerationHostV2';
import { refreshWebPluginGenerationV2 } from '../../plugins/webPluginGenerationV2';
import {
  pluginInstanceServiceV2,
  type PluginInstanceChangeV2,
  type PluginInstanceV2,
  type PluginInstancesResponseV2,
} from '../../services/pluginInstanceServiceV2';

import { PluginConfigFieldsV2 } from './PluginConfigFieldsV2';

interface Props {
  readonly tenantId: string;
  readonly projectId?: string | null;
  readonly canManage: boolean;
  readonly rendererScopeMatches?: boolean;
}

export function PluginInstancesV2({
  tenantId,
  projectId,
  canManage,
  rendererScopeMatches = true,
}: Props) {
  const { t } = useTranslation();
  const renderer = useCurrentWebPluginGenerationStateV2();
  const [snapshot, setSnapshot] = useState<PluginInstancesResponseV2 | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const epoch = useRef(0);
  const applying = useRef(false);
  const request = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    const token = epoch.current;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    setError('');
    try {
      const next = await pluginInstanceServiceV2.list(
        { tenant_id: tenantId, project_id: projectId ?? null },
        controller.signal
      );
      if (token === epoch.current && !controller.signal.aborted) setSnapshot(next);
    } catch (caught) {
      if (token === epoch.current && !controller.signal.aborted)
        setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      if (token === epoch.current && !controller.signal.aborted) setLoading(false);
    }
  }, [tenantId, projectId]);

  useLayoutEffect(() => {
    epoch.current += 1;
    applying.current = false;
    setBusy(false);
    setSnapshot(null);
    setSelected(null);
    setQuery('');
    void refresh();
    return () => {
      epoch.current += 1;
      request.current?.abort();
    };
  }, [refresh]);

  async function apply(change: PluginInstanceChangeV2): Promise<void> {
    if (!snapshot || applying.current || !canManage) return;
    const token = epoch.current;
    request.current?.abort();
    setLoading(false);
    applying.current = true;
    setBusy(true);
    setError('');
    try {
      const next = await pluginInstanceServiceV2.apply(
        { tenant_id: tenantId, project_id: projectId ?? null },
        snapshot.revision,
        [change]
      );
      if (token !== epoch.current) return;
      setSnapshot(next);
      setSelected(null);
      if (rendererScopeMatches)
        void refreshWebPluginGenerationV2().catch(() => {
          if (token === epoch.current) setError(t('plugins.viewSyncFailed'));
        });
    } catch (caught) {
      if (token === epoch.current)
        setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      if (token === epoch.current) {
        applying.current = false;
        setBusy(false);
      }
    }
  }

  const editing = snapshot?.instances.find(({ entry_id }) => entry_id === selected);
  const appliedRevision = rendererScopeMatches
    ? renderer?.generation?.snapshot.generation
    : undefined;
  const rendererStatus = !rendererScopeMatches
    ? 'differentScope'
    : renderer?.status === 'error' || renderer?.status === 'degraded'
      ? 'failed'
      : renderer?.status === 'ready' && appliedRevision === snapshot?.revision
        ? 'applied'
        : 'reconciling';
  const normalized = query.trim().toLocaleLowerCase();
  const visible =
    snapshot?.instances.filter(
      ({ display_name, plugin_id }) =>
        !normalized || `${display_name} ${plugin_id}`.toLocaleLowerCase().includes(normalized)
    ) ?? [];
  return (
    <section
      className="rounded-xl border border-slate-200 dark:border-slate-700 p-5 space-y-4"
      aria-busy={loading || busy}
    >
      <div className="flex justify-between items-center gap-4">
        <div>
          <h2 className="text-lg font-semibold">{t('plugins.instances')}</h2>
          <p>{t('plugins.instancesDescription')}</p>
        </div>
        <button type="button" disabled={loading || busy} onClick={() => void refresh()}>
          {t('common.refresh')}
        </button>
      </div>
      {snapshot ? (
        <div role="status">
          <p>
            {t('plugins.backendPublication')}:{' '}
            {t(`plugins.publicationStates.${snapshot.publication.status}`)}
          </p>
          <p>
            {t('plugins.browserRenderer')}: {t(`plugins.rendererStates.${rendererStatus}`)}
            {appliedRevision === undefined
              ? null
              : ` · ${t('plugins.appliedRevision', { revision: appliedRevision })}`}
          </p>
        </div>
      ) : null}
      <label className="flex flex-col gap-1">
        {t('plugins.searchInstances')}
        <input
          type="search"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
          }}
        />
      </label>
      {loading ? <p role="status">{t('common.loading')}</p> : null}
      {error ? (
        <div role="alert">
          <p>{error}</p>
          <p>{t('plugins.configurationFailure')}</p>
        </div>
      ) : null}
      {snapshot && !loading && visible.length === 0 ? <p>{t('plugins.noInstances')}</p> : null}
      <div className="divide-y divide-slate-200 dark:divide-slate-700">
        {visible.map((instance) => (
          <article key={instance.entry_id} className="py-3 flex justify-between gap-4 items-start">
            <div>
              <h3 className="font-medium">{instance.display_name}</h3>
              <p>
                {t('plugins.desiredState')}:{' '}
                {t(instance.enabled ? 'plugins.enabled' : 'plugins.disabled')}
                {' · '}
                {t('plugins.runtimeState')}: {t(`plugins.runtimeStates.${instance.state.status}`)}
              </p>
              {instance.inherited_from ? <p>{t('plugins.inherited')}</p> : null}
              {instance.reason_code || instance.state.reason_code ? (
                <p>{instance.reason_code || instance.state.reason_code}</p>
              ) : null}
            </div>
            <div className="flex gap-3">
              <button
                type="button"
                disabled={busy || !canManage || !instance.editable}
                aria-label={t(instance.enabled ? 'plugins.disableNamed' : 'plugins.enableNamed', {
                  name: instance.display_name,
                })}
                onClick={() =>
                  void apply({ entry_id: instance.entry_id, enabled: !instance.enabled })
                }
              >
                {t(instance.enabled ? 'plugins.disable' : 'plugins.enable')}
              </button>
              <button
                type="button"
                disabled={
                  busy ||
                  !canManage ||
                  !instance.editable ||
                  (!instance.config_editable && !instance.replacement_candidates.length)
                }
                aria-label={t('plugins.configureNamed', { name: instance.display_name })}
                onClick={() => {
                  setSelected(instance.entry_id);
                }}
              >
                {t('plugins.configure')}
              </button>
            </div>
          </article>
        ))}
      </div>
      {editing ? (
        <PluginInstanceEditorV2
          key={`${tenantId}:${projectId ?? ''}:${editing.entry_id}`}
          instance={editing}
          busy={busy}
          onApply={apply}
          onCancel={() => {
            setSelected(null);
          }}
        />
      ) : null}
    </section>
  );
}

function PluginInstanceEditorV2({
  instance,
  busy,
  onApply,
  onCancel,
}: {
  readonly instance: PluginInstanceV2;
  readonly busy: boolean;
  readonly onApply: (change: PluginInstanceChangeV2) => Promise<void>;
  readonly onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [config, setConfig] = useState<unknown>(instance.config);
  const [invalid, setInvalid] = useState<ReadonlySet<string>>(new Set());
  const [replacement, setReplacement] = useState('');
  const objectConfig = typeof config === 'object' && config !== null && !Array.isArray(config);
  return (
    <form
      className="border rounded-lg p-4 space-y-4"
      aria-label={t('plugins.configureNamed', { name: instance.display_name })}
      onSubmit={(event) => {
        event.preventDefault();
        const candidate = instance.replacement_candidates.find(
          (_, index) => String(index) === replacement
        );
        void onApply({
          entry_id: instance.entry_id,
          ...(instance.config_editable && objectConfig
            ? { config: config as Record<string, unknown> }
            : {}),
          ...(candidate ? { replacement: candidate } : {}),
        });
      }}
    >
      <h3>{t('plugins.configureNamed', { name: instance.display_name })}</h3>
      <fieldset disabled={busy} className="space-y-4">
        {instance.config_editable ? (
          <PluginConfigFieldsV2
            schema={instance.config_schema}
            value={config}
            name=""
            onChange={setConfig}
            onValidity={(path, valid) => {
              setInvalid((previous) => {
                const next = new Set(previous);
                if (valid) next.delete(path);
                else next.add(path);
                return next;
              });
            }}
          />
        ) : (
          <p>{t('plugins.privateConfiguration')}</p>
        )}
        {instance.replacement_candidates.length ? (
          <label className="flex flex-col gap-1">
            {t('plugins.replacement')}
            <select
              value={replacement}
              onChange={(event) => {
                setReplacement(event.target.value);
              }}
            >
              <option value="">{t('plugins.keepImplementation')}</option>
              {instance.replacement_candidates.map((candidate, index) => (
                <option key={`${candidate.plugin_id}:${candidate.module_ref}`} value={index}>
                  {candidate.plugin_id} · {candidate.module_ref}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <div className="flex gap-3">
          <button
            type="submit"
            disabled={
              invalid.size > 0 ||
              (instance.config_editable && !objectConfig) ||
              (!instance.config_editable && !replacement)
            }
          >
            {t('common.save')}
          </button>
          <button type="button" onClick={onCancel}>
            {t('common.cancel')}
          </button>
        </div>
      </fieldset>
    </form>
  );
}
