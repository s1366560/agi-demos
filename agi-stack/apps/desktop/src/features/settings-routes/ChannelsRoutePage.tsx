import { useMemo, useState } from 'react';
import { CheckCircledIcon, PlusIcon, ReloadIcon, TrashIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  CreateManagedChannelConfigRequest,
  ManagedChannelConfig,
  ManagedChannelPluginConfigSchema,
  UpdateManagedChannelConfigRequest,
} from '../../types';
import {
  channelConnectionDraftFrom,
  channelConnectionFields,
  channelConnectionMutationFromDraft,
  validateChannelConnectionDraft,
  type ChannelConnectionDraft,
  type ChannelConnectionErrors,
  type ChannelConnectionField,
} from '../settings/channelConnectionModel';
import type { ChannelsRouteController } from './channelsRouteController';
import type { ChannelsRoutePresentationModel } from './channelsRoutePresentationModel';
import { useNativeRouteAction } from './useNativeRouteAction';

type ChannelEditor = Readonly<{
  target: ManagedChannelConfig | null;
  schema: ManagedChannelPluginConfigSchema;
  draft: ChannelConnectionDraft;
}>;

export function ChannelsRoutePage({
  model,
  controller,
}: Readonly<{
  model: ChannelsRoutePresentationModel;
  controller: ChannelsRouteController;
}>) {
  const { t } = useI18n();
  const observation = model.observation;
  const action = useNativeRouteAction('project_channels_action_failed');
  const [editor, setEditor] = useState<ChannelEditor | null>(null);
  const [errors, setErrors] = useState<ChannelConnectionErrors>({});
  const [notice, setNotice] = useState<string | null>(null);
  const allowed = useMemo(
    () => new Set(observation?.allowedActions ?? []),
    [observation?.allowedActions],
  );
  if (!observation) return <ContractGap capability={model.capability} />;
  const busy = action.busyAction !== null;

  const openEditor = async (
    channelType: string,
    target: ManagedChannelConfig | null,
  ): Promise<void> => {
    const result = await action.run(`schema:${channelType}`, () =>
      controller.getSchema(model.scope, channelType),
    );
    if (!result.ok) return;
    setErrors({});
    setEditor({
      target,
      schema: result.value,
      draft: channelConnectionDraftFrom(result.value, target),
    });
  };

  const submit = async (): Promise<void> => {
    if (!editor) return;
    const nextErrors = validateChannelConnectionDraft(
      editor.schema,
      editor.draft,
      editor.target !== null,
    );
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;
    const mutation = channelConnectionMutationFromDraft(
      editor.schema,
      editor.draft,
      editor.target !== null,
    );
    const result = editor.target
      ? await action.run(`update:${editor.target.id}`, () =>
          controller.update(
            model.scope,
            editor.target!.id,
            mutation as UpdateManagedChannelConfigRequest,
          ),
        )
      : await action.run('create', () =>
          controller.create(model.scope, mutation as CreateManagedChannelConfigRequest),
        );
    if (result.ok) setEditor(null);
  };

  return (
    <main className="settings-page" data-route-content="channels" data-state={model.state}>
      <header className="settings-page-heading">
        <div>
          <span>{t('settings.pluginsEyebrow')}</span>
          <h1>{t('settings.channels.title')}</h1>
          <p>{t('settings.channels.description')}</p>
        </div>
        <button
          type="button"
          data-action="create-channel-config"
          disabled={
            busy || !allowed.has('create-channel-config') || observation.catalog.length === 0
          }
          onClick={() => {
            const first = observation.catalog.find((item) => item.enabled && item.discovered);
            if (first) void openEditor(first.channel_type, null);
          }}
        >
          <PlusIcon /> {t('settings.channels.add')}
        </button>
      </header>

      {action.reasonCode ? <code role="alert">{action.reasonCode}</code> : null}
      {notice ? <span role="status">{notice}</span> : null}

      <section className="settings-panel" data-action="view-channel-catalog">
        <header>
          <strong>{t('settings.channels.type')}</strong>
        </header>
        <div className="settings-list">
          {observation.catalog.map((item) => (
            <article key={item.channel_type}>
              <div>
                <strong>{item.channel_type}</strong>
                <code>{item.plugin_name}</code>
              </div>
              <button
                type="button"
                data-action="view-channel-schema"
                disabled={busy || !allowed.has('view-channel-schema')}
                onClick={() => void openEditor(item.channel_type, null)}
              >
                {t('settings.channels.add')}
              </button>
            </article>
          ))}
        </div>
      </section>

      {editor ? (
        <ChannelEditorForm
          editor={editor}
          errors={errors}
          disabled={busy}
          onChange={(draft) => setEditor((current) => (current ? { ...current, draft } : current))}
          onCancel={() => setEditor(null)}
          onSubmit={() => void submit()}
        />
      ) : null}

      <section className="settings-panel" data-action="list-channel-configs">
        {observation.configs.length === 0 ? (
          <p>{t('settings.channels.empty')}</p>
        ) : (
          <div className="settings-list">
            {observation.configs.map((config) => (
              <article key={config.id}>
                <div>
                  <strong>{config.name}</strong>
                  <code>{config.channel_type}</code>
                  <span>
                    {config.status === 'connected' ? <CheckCircledIcon /> : null}
                    {t(`settings.channels.status.${config.status}`)}
                  </span>
                  {config.last_error ? <small>{config.last_error}</small> : null}
                </div>
                <div>
                  <button
                    type="button"
                    data-action="update-channel-config"
                    disabled={busy || !allowed.has('update-channel-config')}
                    onClick={() => void openEditor(config.channel_type, config)}
                  >
                    {t('common.edit')}
                  </button>
                  <button
                    type="button"
                    data-action="test-channel-config"
                    disabled={busy || !config.enabled || !allowed.has('test-channel-config')}
                    onClick={() =>
                      void action
                        .run(`test:${config.id}`, () => controller.test(model.scope, config.id))
                        .then((result) => {
                          if (result.ok) {
                            setNotice(
                              t(
                                result.value.success
                                  ? 'settings.channels.notice.testSuccess'
                                  : 'settings.channels.notice.testFailure',
                                { message: result.value.message },
                              ),
                            );
                          }
                        })
                    }
                  >
                    {action.busyAction === `test:${config.id}` ? <ReloadIcon /> : null}
                    {t('settings.channels.test')}
                  </button>
                  <button
                    type="button"
                    data-action="delete-channel-config"
                    aria-label={t('settings.channels.deleteNamed', { name: config.name })}
                    disabled={busy || !allowed.has('delete-channel-config')}
                    onClick={() =>
                      void action.run(`delete:${config.id}`, () =>
                        controller.remove(model.scope, config.id),
                      )
                    }
                  >
                    <TrashIcon />
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

function ChannelEditorForm({
  editor,
  errors,
  disabled,
  onChange,
  onCancel,
  onSubmit,
}: Readonly<{
  editor: ChannelEditor;
  errors: ChannelConnectionErrors;
  disabled: boolean;
  onChange: (draft: ChannelConnectionDraft) => void;
  onCancel: () => void;
  onSubmit: () => void;
}>) {
  const { t } = useI18n();
  const fields = useMemo(() => channelConnectionFields(editor.schema), [editor.schema]);
  const updateValue = (name: string, value: unknown): void => {
    onChange({
      ...editor.draft,
      ...(name === 'name'
        ? { name: String(value) }
        : { values: { ...editor.draft.values, [name]: value } }),
    });
  };
  return (
    <form
      className="settings-panel"
      data-action={editor.target ? 'update-channel-config' : 'create-channel-config'}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <label>
        <span>{t('settings.channels.type')}</span>
        <input value={editor.draft.channelType} disabled />
      </label>
      <label>
        <span>{t('settings.channels.name')}</span>
        <input
          value={editor.draft.name}
          disabled={disabled}
          onChange={(event) => updateValue('name', event.currentTarget.value)}
        />
        {errors.name ? <em role="alert">{t('settings.channels.error.required')}</em> : null}
      </label>
      <label>
        <span>{t('settings.channels.descriptionField')}</span>
        <input
          value={editor.draft.description}
          disabled={disabled}
          onChange={(event) =>
            onChange({ ...editor.draft, description: event.currentTarget.value })
          }
        />
      </label>
      <label>
        <input
          type="checkbox"
          checked={editor.draft.enabled}
          disabled={disabled}
          onChange={(event) => onChange({ ...editor.draft, enabled: event.currentTarget.checked })}
        />
        {t('settings.channels.enabled')}
      </label>
      {fields.map((field) => (
        <ChannelSchemaField
          key={field.name}
          field={field}
          value={editor.draft.values[field.name]}
          error={errors[field.name]}
          editing={editor.target !== null}
          disabled={disabled}
          onChange={(value) => updateValue(field.name, value)}
        />
      ))}
      <footer>
        <button type="button" disabled={disabled} onClick={onCancel}>
          {t('common.cancel')}
        </button>
        <button type="submit" disabled={disabled}>
          {editor.target ? t('common.save') : t('common.create')}
        </button>
      </footer>
    </form>
  );
}

function ChannelSchemaField({
  field,
  value,
  error,
  editing,
  disabled,
  onChange,
}: Readonly<{
  field: ChannelConnectionField;
  value: unknown;
  error: string | undefined;
  editing: boolean;
  disabled: boolean;
  onChange: (value: unknown) => void;
}>) {
  const { t } = useI18n();
  if (field.kind === 'boolean') {
    return (
      <label>
        <input
          type="checkbox"
          checked={value === true}
          disabled={disabled}
          onChange={(event) => onChange(event.currentTarget.checked)}
        />
        <span>{field.label}</span>
      </label>
    );
  }
  return (
    <label>
      <span>{field.label}</span>
      {field.kind === 'select' ? (
        <select
          value={String(value ?? '')}
          disabled={disabled}
          onChange={(event) => onChange(event.currentTarget.value)}
        >
          <option value="">{t('settings.channels.selectOption')}</option>
          {field.options.map((option) => (
            <option key={String(option)} value={String(option)}>
              {String(option)}
            </option>
          ))}
        </select>
      ) : (
        <input
          type={field.kind === 'secret' ? 'password' : field.kind === 'text' ? 'text' : 'number'}
          value={typeof value === 'string' || typeof value === 'number' ? value : ''}
          min={field.minimum ?? undefined}
          max={field.maximum ?? undefined}
          step={field.kind === 'integer' ? 1 : field.kind === 'number' ? 'any' : undefined}
          placeholder={
            field.kind === 'secret' && editing
              ? t('settings.channels.secretPlaceholder')
              : field.placeholder
          }
          disabled={disabled}
          onChange={(event) => onChange(event.currentTarget.value)}
        />
      )}
      {field.help ? <small>{field.help}</small> : null}
      {error ? <em role="alert">{t(`settings.channels.error.${error}`)}</em> : null}
    </label>
  );
}

function ContractGap({ capability }: Readonly<{ capability: string }>) {
  return (
    <section className="desktop-production-route-boundary" data-state="unavailable">
      <code>{capability}:presentation_observation_unavailable</code>
    </section>
  );
}
