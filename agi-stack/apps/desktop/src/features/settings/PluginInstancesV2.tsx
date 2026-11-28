import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

import type {
  PluginInstanceChangeV2,
  PluginInstanceV2,
  PluginInstancesResponseV2,
} from '../../api/pluginInstanceClientV2';
import { useI18n } from '../../i18n';
import type { DesktopPluginMarketplaceOperationsV2 } from '../../plugins/desktopPluginMarketplaceAuthorityModulesV2';
import type { DesktopRuntimeConfig } from '../../types';
import './PluginInstancesV2.css';

const messages = {
  'en-US': {
    title: 'Plugin instances',
    description:
      'Configure the active tenant or project. Changes apply together against the displayed revision.',
    refresh: 'Refresh',
    enabled: 'Enabled',
    save: 'Apply changes',
    reset: 'Discard changes',
    replacement: 'Implementation',
    current: 'Current implementation',
    empty: 'No plugin instances in this scope.',
    invalid: 'Configuration must be valid JSON matching the displayed schema.',
    revision: 'Revision',
    readonly: 'Read only',
    inherited: 'Inherited',
    config: 'Configuration',
    schema: 'Configuration schema',
    state: 'Publication',
    unavailable: 'Select a tenant and project to configure local instances.',
    search: 'Search plugin instances',
    showReadonly: 'Show deployment-managed instances',
    list: 'Configurable plugin instances',
    noMatches: 'No matching plugin instances.',
  },
  'zh-CN': {
    title: '插件实例',
    description: '配置当前租户或项目。修改将按所示修订号一起应用。',
    refresh: '刷新',
    enabled: '启用',
    save: '应用修改',
    reset: '放弃修改',
    replacement: '实现',
    current: '当前实现',
    empty: '此作用域没有插件实例。',
    invalid: '配置必须是符合所示 schema 的有效 JSON。',
    revision: '修订号',
    readonly: '只读',
    inherited: '继承',
    config: '配置',
    schema: '配置 Schema',
    state: '发布状态',
    unavailable: '选择租户和项目后可配置本地实例。',
    search: '搜索插件实例',
    showReadonly: '显示部署管理的只读实例',
    list: '可配置的插件实例',
    noMatches: '没有匹配的插件实例。',
  },
} as const;

export function PluginInstancesV2({
  config,
  operations,
  canManage,
}: {
  config: DesktopRuntimeConfig;
  operations: Pick<DesktopPluginMarketplaceOperationsV2, 'instanceClient'>;
  canManage: boolean;
}) {
  const { locale } = useI18n();
  const copy = messages[locale === 'zh-CN' ? 'zh-CN' : 'en-US'];
  const client = useMemo(
    () =>
      config.tenantId && (config.mode === 'cloud' || config.projectId)
        ? operations.instanceClient(config)
        : null,
    [config, operations],
  );
  const [response, setResponse] = useState<PluginInstancesResponseV2 | null>(null);
  const [drafts, setDrafts] = useState<Record<string, PluginInstanceChangeV2>>({});
  const [invalidInstances, setInvalidInstances] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [query, setQuery] = useState('');
  const [showReadonly, setShowReadonly] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const currentClient = useRef(client);
  currentClient.current = client;
  useLayoutEffect(() => {
    const abort = new AbortController();
    controller.current?.abort();
    controller.current = abort;
    setResponse(null);
    setDrafts({});
    setInvalidInstances({});
    setError(null);
    setBusy(Boolean(client));
    if (client)
      void client
        .list(abort.signal)
        .then((value) => {
          if (!abort.signal.aborted) setResponse(value);
        })
        .catch((caught: unknown) => {
          if (!abort.signal.aborted)
            setError(caught instanceof Error ? caught.message : String(caught));
        })
        .finally(() => {
          if (!abort.signal.aborted) setBusy(false);
        });
    return () => {
      abort.abort();
      controller.current?.abort();
    };
  }, [client, reload]);
  useEffect(() => {
    if (response?.publication.status !== 'reconciling') return;
    const timer = window.setTimeout(() => setReload((value) => value + 1), 1500);
    return () => window.clearTimeout(timer);
  }, [response]);
  const instances = useMemo(
    () =>
      [...(response?.instances ?? [])].sort(
        (left, right) =>
          Number(right.editable) - Number(left.editable) ||
          left.display_name.localeCompare(right.display_name),
      ),
    [response],
  );
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visible = (instance: PluginInstanceV2) =>
    (showReadonly || instance.editable) &&
    `${instance.display_name} ${instance.entry_id}`.toLocaleLowerCase().includes(normalizedQuery);
  const save = async () => {
    if (!client || !response || busy || !canManage || Object.values(invalidInstances).some(Boolean))
      return;
    const abort = new AbortController();
    controller.current?.abort();
    controller.current = abort;
    setBusy(true);
    setError(null);
    try {
      const value = await client.apply(response.revision, Object.values(drafts), abort.signal);
      if (!abort.signal.aborted && currentClient.current === client) {
        setResponse(value);
        setDrafts({});
        window.dispatchEvent(new Event('memstack:plugin-configuration-changed-v2'));
      }
    } catch (caught) {
      if (!abort.signal.aborted && currentClient.current === client)
        setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      if (!abort.signal.aborted && currentClient.current === client) setBusy(false);
    }
  };
  return (
    <section className="plugin-instances-v2" aria-busy={busy}>
      <h2>{copy.title}</h2>
      <p>{copy.description}</p>
      {!client ? <p>{copy.unavailable}</p> : null}
      {response ? (
        <p>
          {response.scope.tenant_id} / {response.scope.project_id ?? 'tenant'} · {copy.revision}{' '}
          {response.revision} · {copy.state}: {response.publication.status}
        </p>
      ) : null}
      <button disabled={!client || busy} onClick={() => setReload((value) => value + 1)}>
        {copy.refresh}
      </button>
      {error ? <p role="alert">{error}</p> : null}
      {response?.instances.length === 0 ? <p>{copy.empty}</p> : null}
      <div className="plugin-instances-v2__filters">
        <label>
          {copy.search}
          <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
        <label className="plugin-instances-v2__checkbox">
          <input
            type="checkbox"
            checked={showReadonly}
            onChange={(event) => setShowReadonly(event.target.checked)}
          />
          {copy.showReadonly}
        </label>
      </div>
      <div className="plugin-instances-v2__list" role="region" aria-label={copy.list}>
        {response && !instances.some(visible) ? <p>{copy.noMatches}</p> : null}
        {instances.map((instance) => (
          <PluginInstanceFormV2
            key={`${response?.revision}:${instance.entry_id}`}
            instance={instance}
            hidden={!visible(instance)}
            disabled={busy || !canManage}
            copy={copy}
            onValidityChange={(valid) =>
              setInvalidInstances((current) => ({
                ...current,
                [instance.entry_id]: !valid,
              }))
            }
            onChange={(change) =>
              setDrafts((current) => ({
                ...current,
                [instance.entry_id]: { ...current[instance.entry_id], ...change },
              }))
            }
          />
        ))}
      </div>
      <div className="plugin-instances-v2__actions">
        <button
          disabled={
            busy ||
            !canManage ||
            Object.keys(drafts).length === 0 ||
            Object.values(invalidInstances).some(Boolean)
          }
          onClick={() => void save()}
        >
          {copy.save}
        </button>
        <button
          disabled={
            busy ||
            (Object.keys(drafts).length === 0 && !Object.values(invalidInstances).some(Boolean))
          }
          onClick={() => setReload((value) => value + 1)}
        >
          {copy.reset}
        </button>
      </div>
    </section>
  );
}

type Copy = { readonly [K in keyof (typeof messages)['en-US']]: string };
function PluginInstanceFormV2({
  instance,
  hidden,
  disabled,
  copy,
  onChange,
  onValidityChange,
}: {
  instance: PluginInstanceV2;
  hidden: boolean;
  disabled: boolean;
  copy: Copy;
  onChange: (change: PluginInstanceChangeV2) => void;
  onValidityChange: (valid: boolean) => void;
}) {
  const [config, setConfig] = useState<Record<string, unknown>>({
    ...instance.config,
  });
  const [invalidFields, setInvalidFields] = useState<Record<string, boolean>>({});
  const validateField = (name: string, valid: boolean) => {
    const next = { ...invalidFields, [name]: !valid };
    setInvalidFields(next);
    onValidityChange(!Object.values(next).some(Boolean));
  };
  const properties = isRecord(instance.config_schema.properties)
    ? instance.config_schema.properties
    : {};
  const changeField = (name: string, value: unknown) => {
    const next = { ...config, [name]: value };
    setConfig(next);
    validateField(name, true);
    onChange({ entry_id: instance.entry_id, config: next });
  };
  return (
    <fieldset
      hidden={hidden}
      disabled={disabled || !instance.editable}
      className="plugin-instances-v2__instance"
    >
      <legend>{instance.display_name}</legend>
      <code>{instance.entry_id}</code>
      <p>
        {instance.state.status} {instance.reason_code ?? ''}{' '}
        {instance.inherited_from ? copy.inherited : ''} {!instance.editable ? copy.readonly : ''}
      </p>
      <label>
        <input
          type="checkbox"
          defaultChecked={instance.enabled}
          onChange={(event) =>
            onChange({
              entry_id: instance.entry_id,
              enabled: event.target.checked,
            })
          }
        />
        {copy.enabled}
      </label>
      {instance.replacement_candidates.length > 0 ? (
        <label>
          {copy.replacement}
          <select
            defaultValue=""
            onChange={(event) => {
              const replacement = instance.replacement_candidates.find(
                (item) => item.module_ref === event.target.value,
              );
              onChange({ entry_id: instance.entry_id, replacement });
            }}
          >
            <option value="">{copy.current}</option>
            {instance.replacement_candidates.map((item) => (
              <option key={item.module_ref} value={item.module_ref}>
                {item.plugin_id}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {Object.entries(properties).map(([name, raw]) => {
        if (!isRecord(raw)) return null;
        const inputId = `plugin-config-${instance.entry_id}-${name}`;
        const locked =
          disabled || !instance.config_editable || raw.readOnly === true || raw.writeOnly === true;
        const value = config[name] ?? raw.default ?? '';
        return (
          <label key={name} htmlFor={inputId}>
            {typeof raw.title === 'string' ? raw.title : name}
            {Array.isArray(raw.enum) ? (
              <select
                id={inputId}
                disabled={locked}
                value={JSON.stringify(value)}
                onChange={(event) => changeField(name, JSON.parse(event.target.value))}
              >
                {raw.enum.map((item) => (
                  <option key={JSON.stringify(item)} value={JSON.stringify(item)}>
                    {String(item)}
                  </option>
                ))}
              </select>
            ) : raw.type === 'boolean' ? (
              <input
                id={inputId}
                disabled={locked}
                type="checkbox"
                checked={value === true}
                onChange={(event) => changeField(name, event.target.checked)}
              />
            ) : raw.type === 'number' || raw.type === 'integer' ? (
              <input
                id={inputId}
                disabled={locked}
                type="number"
                step={raw.type === 'integer' ? 1 : 'any'}
                defaultValue={String(value)}
                min={typeof raw.minimum === 'number' ? raw.minimum : undefined}
                max={typeof raw.maximum === 'number' ? raw.maximum : undefined}
                onChange={(event) => {
                  if (event.target.validity.valid && Number.isFinite(event.target.valueAsNumber))
                    changeField(name, event.target.valueAsNumber);
                  else validateField(name, false);
                }}
              />
            ) : raw.type === 'object' || raw.type === 'array' ? (
              <textarea
                id={inputId}
                disabled={locked}
                defaultValue={JSON.stringify(value, null, 2)}
                onChange={(event) => {
                  try {
                    const parsed: unknown = JSON.parse(event.target.value);
                    if (raw.type === 'array' ? !Array.isArray(parsed) : !isRecord(parsed))
                      throw new Error('invalid_config_type');
                    changeField(name, parsed);
                  } catch {
                    validateField(name, false);
                  }
                }}
              />
            ) : (
              <input
                id={inputId}
                disabled={locked}
                value={typeof value === 'string' ? value : ''}
                onChange={(event) => changeField(name, event.target.value)}
              />
            )}
          </label>
        );
      })}
      <details>
        <summary>{copy.schema}</summary>
        <pre>{JSON.stringify(instance.config_schema, null, 2)}</pre>
      </details>
      {Object.values(invalidFields).some(Boolean) ? <p role="alert">{copy.invalid}</p> : null}
    </fieldset>
  );
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
