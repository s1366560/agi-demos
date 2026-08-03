import { useState } from 'react';

import { PlusIcon, TrashIcon } from '@radix-ui/react-icons';
import { Button, Switch, TextArea, TextField } from '@radix-ui/themes';

import { useI18n } from '../../i18n';
import type {
  TenantRuntimeHook,
  TenantRuntimeHookCatalogEntry,
} from './tenantAgentDashboardClient';
import {
  buildEditableRuntimeHooks,
  createCustomRuntimeHook,
  parseRuntimeHookSettings,
  serializeRuntimeHooks,
  validateRuntimeHook,
} from './tenantAgentDashboardHooks';
import './TenantAgentDashboardHookEditor.css';

type HookDraft = Readonly<{
  hook: TenantRuntimeHook;
  settingsText: string;
  settingsReason: string | null;
}>;

export function TenantAgentDashboardHookEditor({
  configuredHooks,
  catalog,
  onChange,
  onValidityChange,
}: Readonly<{
  configuredHooks: readonly TenantRuntimeHook[];
  catalog: readonly TenantRuntimeHookCatalogEntry[];
  onChange: (hooks: readonly TenantRuntimeHook[]) => void;
  onValidityChange: (valid: boolean) => void;
}>) {
  const { t } = useI18n();
  const initial = buildEditableRuntimeHooks(configuredHooks, catalog);
  const [managed, setManaged] = useState<readonly HookDraft[]>(() => initial.managed.map(toDraft));
  const [custom, setCustom] = useState<readonly HookDraft[]>(() => initial.custom.map(toDraft));

  const publish = (nextManaged: readonly HookDraft[], nextCustom: readonly HookDraft[]): void => {
    const drafts = [...nextManaged, ...nextCustom];
    const valid = drafts.every(
      (draft) => draft.settingsReason === null && validateRuntimeHook(draft.hook).length === 0,
    );
    onValidityChange(valid);
    if (!valid) return;
    onChange(
      serializeRuntimeHooks(
        nextManaged.map(({ hook }) => hook),
        nextCustom.map(({ hook }) => hook),
        catalog,
      ),
    );
  };

  const updateManaged = (index: number, update: (draft: HookDraft) => HookDraft): void => {
    const next = managed.map((draft, candidate) => (candidate === index ? update(draft) : draft));
    setManaged(Object.freeze(next));
    publish(next, custom);
  };
  const updateCustom = (index: number, update: (draft: HookDraft) => HookDraft): void => {
    const next = custom.map((draft, candidate) => (candidate === index ? update(draft) : draft));
    setCustom(Object.freeze(next));
    publish(managed, next);
  };

  return (
    <section className="tenant-agent-dashboard-hook-editor">
      <header>
        <div>
          <span>{t('tenantAgentDashboard.hooks.editorEyebrow')}</span>
          <h3>{t('tenantAgentDashboard.hooks.editorTitle')}</h3>
          <p>{t('tenantAgentDashboard.hooks.editorDescription')}</p>
        </div>
        <Button
          type="button"
          color="gray"
          variant="soft"
          onClick={() => {
            const next = Object.freeze([...custom, toDraft(createCustomRuntimeHook())]);
            setCustom(next);
            publish(managed, next);
          }}
        >
          <PlusIcon />
          {t('tenantAgentDashboard.hooks.addCustom')}
        </Button>
      </header>
      <div className="tenant-agent-dashboard-hook-editor-list">
        {managed.map((draft, index) => (
          <RuntimeHookEditor
            key={catalog[index]?.key ?? `managed-${String(index)}`}
            draft={draft}
            catalogEntry={catalog[index] ?? null}
            custom={false}
            onChange={(update) => updateManaged(index, update)}
          />
        ))}
        {custom.map((draft, index) => (
          <RuntimeHookEditor
            key={`custom-${String(index)}`}
            draft={draft}
            catalogEntry={null}
            custom
            onChange={(update) => updateCustom(index, update)}
            onRemove={() => {
              const next = custom.filter((_, candidate) => candidate !== index);
              setCustom(Object.freeze(next));
              publish(managed, next);
            }}
          />
        ))}
      </div>
    </section>
  );
}

function RuntimeHookEditor({
  draft,
  catalogEntry,
  custom,
  onChange,
  onRemove,
}: Readonly<{
  draft: HookDraft;
  catalogEntry: TenantRuntimeHookCatalogEntry | null;
  custom: boolean;
  onChange: (update: (draft: HookDraft) => HookDraft) => void;
  onRemove?: () => void;
}>) {
  const { t } = useI18n();
  const reasons = validateRuntimeHook(draft.hook);
  const schemaFields = catalogEntry ? schemaPropertyNames(catalogEntry.settingsSchema) : [];
  const patchHook = (patch: Partial<TenantRuntimeHook>): void => {
    onChange((current) =>
      Object.freeze({
        ...current,
        hook: Object.freeze({ ...current.hook, ...patch }),
      }),
    );
  };
  return (
    <article className="tenant-agent-dashboard-hook-editor-card">
      <header>
        <div>
          <strong>
            {catalogEntry?.displayName ||
              draft.hook.hookName ||
              t('tenantAgentDashboard.hooks.customUntitled')}
          </strong>
          <code>
            {catalogEntry?.key ||
              `${draft.hook.pluginName || draft.hook.sourceRef || 'custom'}.${draft.hook.hookName || 'new'}`}
          </code>
        </div>
        <div>
          <label>
            <span>{t('common.enabled')}</span>
            <Switch
              checked={draft.hook.enabled}
              onCheckedChange={(enabled) => patchHook({ enabled })}
            />
          </label>
          {custom ? (
            <Button
              type="button"
              color="red"
              variant="ghost"
              aria-label={t('tenantAgentDashboard.hooks.removeCustom')}
              onClick={onRemove}
            >
              <TrashIcon />
            </Button>
          ) : null}
        </div>
      </header>
      {catalogEntry?.description ? <p>{catalogEntry.description}</p> : null}
      <div className="tenant-agent-dashboard-hook-editor-fields">
        <HookTextField
          label={t('tenantAgentDashboard.hooks.hookName')}
          value={draft.hook.hookName}
          disabled={!custom}
          onChange={(hookName) => patchHook({ hookName })}
        />
        <HookTextField
          label={t('tenantAgentDashboard.hooks.pluginName')}
          value={draft.hook.pluginName}
          disabled={!custom}
          onChange={(pluginName) => patchHook({ pluginName })}
        />
        <HookSelect
          label={t('tenantAgentDashboard.hooks.family')}
          value={draft.hook.hookFamily ?? ''}
          options={['observational', 'mutating', 'policy', 'side_effect']}
          onChange={(hookFamily) => patchHook({ hookFamily })}
        />
        <HookSelect
          label={t('tenantAgentDashboard.hooks.executor')}
          value={draft.hook.executorKind}
          options={['builtin', 'script', 'plugin']}
          onChange={(executorKind) => patchHook({ executorKind })}
        />
        <HookTextField
          label={t('tenantAgentDashboard.hooks.source')}
          value={draft.hook.sourceRef ?? ''}
          onChange={(sourceRef) => patchHook({ sourceRef })}
        />
        <HookTextField
          label={t('tenantAgentDashboard.hooks.entrypoint')}
          value={draft.hook.entrypoint ?? ''}
          onChange={(entrypoint) => patchHook({ entrypoint })}
        />
        <label>
          <span>{t('tenantAgentDashboard.hooks.priority')}</span>
          <TextField.Root
            type="number"
            value={draft.hook.priority === null ? '' : String(draft.hook.priority)}
            onChange={(event) =>
              patchHook({
                priority: event.target.value === '' ? null : Number(event.target.value),
              })
            }
          />
        </label>
      </div>
      <label className="tenant-agent-dashboard-hook-settings">
        <span>{t('tenantAgentDashboard.hooks.settings')}</span>
        {schemaFields.length ? (
          <small>
            {t('tenantAgentDashboard.hooks.schemaFields', {
              fields: schemaFields.join(', '),
            })}
          </small>
        ) : null}
        <TextArea
          rows={5}
          value={draft.settingsText}
          onChange={(event) => {
            const parsed = parseRuntimeHookSettings(event.target.value);
            onChange((current) =>
              Object.freeze({
                hook: Object.freeze({
                  ...current.hook,
                  settings: parsed.settings,
                }),
                settingsText: event.target.value,
                settingsReason: parsed.reasonCode,
              }),
            );
          }}
        />
      </label>
      {draft.settingsReason || reasons.length ? (
        <div className="tenant-agent-dashboard-hook-errors" role="alert">
          {[draft.settingsReason, ...reasons]
            .filter((reason): reason is string => reason !== null)
            .map((reason) => (
              <code key={reason}>{reason}</code>
            ))}
        </div>
      ) : null}
    </article>
  );
}

function HookTextField({
  label,
  value,
  disabled = false,
  onChange,
}: Readonly<{
  label: string;
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}>) {
  return (
    <label>
      <span>{label}</span>
      <TextField.Root
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function HookSelect({
  label,
  value,
  options,
  onChange,
}: Readonly<{
  label: string;
  value: string;
  options: readonly string[];
  onChange: (value: string) => void;
}>) {
  return (
    <label>
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function toDraft(hook: TenantRuntimeHook): HookDraft {
  return Object.freeze({
    hook,
    settingsText: JSON.stringify(hook.settings, null, 2),
    settingsReason: null,
  });
}

function schemaPropertyNames(schema: Readonly<Record<string, unknown>>): readonly string[] {
  const properties = schema.properties;
  return typeof properties === 'object' && properties !== null && !Array.isArray(properties)
    ? Object.keys(properties).sort()
    : Object.freeze([]);
}
