import { useMemo, useRef, useState } from 'react';
import {
  CheckCircledIcon,
  ComponentInstanceIcon,
  Cross2Icon,
  ExclamationTriangleIcon,
  Pencil2Icon,
  PlusIcon,
  ReloadIcon,
  TrashIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { ManagedChannelConfig } from '../../types';
import {
  channelConnectionDraftFrom,
  channelConnectionFields,
  channelConnectionMutationFromDraft,
  validateChannelConnectionDraft,
  type ChannelConnectionDraft,
  type ChannelConnectionErrors,
  type ChannelConnectionField,
} from './channelConnectionModel';
import { useModalDialog } from './useModalDialog';
import type { useChannelConnectionManagement } from './useChannelConnectionManagement';

import './PluginManagementDialogs.css';
import './ChannelConnectionsDialog.css';

export function ChannelConnectionsDialog({
  management,
}: {
  management: ReturnType<typeof useChannelConnectionManagement>;
}) {
  const { t } = useI18n();
  const dialogRef = useModalDialog({
    active: management.open,
    nested: true,
    onClose: management.close,
  });
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  if (!management.open) return null;
  const notice = management.notice?.startsWith('testFailure:')
    ? t('settings.channels.notice.testFailure', {
        message: management.notice.slice('testFailure:'.length),
      })
    : management.notice
      ? t(`settings.channels.notice.${management.notice}`)
      : null;

  return (
    <div className="plugin-management-backdrop" role="presentation">
      <section
        ref={dialogRef}
        className="plugin-management-dialog channel-connections-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={t('settings.channels.title')}
        tabIndex={-1}
      >
        <header className="plugin-management-heading">
          <ComponentInstanceIcon />
          <div>
            <span>{t('settings.pluginsEyebrow')}</span>
            <h2>{t('settings.channels.title')}</h2>
            <p>{t('settings.channels.description')}</p>
          </div>
          <button
            type="button"
            aria-label={t('common.close')}
            disabled={management.busyId !== null}
            onClick={management.close}
          >
            <Cross2Icon />
          </button>
        </header>
        {management.editor ? (
          <ChannelConnectionEditor key={management.editor.key} management={management} />
        ) : (
          <>
            <div className="channel-connections-toolbar">
              <div>
                {notice ? <span role="status">{notice}</span> : null}
                {management.error ? <em role="alert">{management.error}</em> : null}
              </div>
              <button
                type="button"
                className="primary"
                disabled={management.loading || management.catalog.length === 0}
                onClick={management.openCreate}
              >
                <PlusIcon /> {t('settings.channels.add')}
              </button>
            </div>
            <div className="plugin-management-body channel-connections-body">
              {management.loading ? (
                <div className="plugin-management-state">
                  <ReloadIcon className="managed-resource-spin" />
                  <span>{t('settings.channels.loading')}</span>
                </div>
              ) : management.configs.length === 0 ? (
                <div className="plugin-management-state">
                  <ComponentInstanceIcon />
                  <span>{t('settings.channels.empty')}</span>
                </div>
              ) : (
                <div className="channel-connections-list">
                  {management.configs.map((channel) => {
                    const busy = management.busyId === channel.id;
                    const deleting = confirmDeleteId === channel.id;
                    return (
                      <article key={channel.id}>
                        <div className="channel-connection-summary">
                          <span className={`channel-status ${channel.status}`}>
                            {channel.status === 'connected' ? (
                              <CheckCircledIcon />
                            ) : (
                              <ExclamationTriangleIcon />
                            )}
                            {t(`settings.channels.status.${channel.status}`)}
                          </span>
                          <h3>{channel.name}</h3>
                          <p>{channel.channel_type}</p>
                          {channel.last_error ? <small>{channel.last_error}</small> : null}
                        </div>
                        <div className="channel-connection-actions">
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => management.toggle(channel)}
                          >
                            {channel.enabled
                              ? t('settings.channels.disable')
                              : t('settings.channels.enable')}
                          </button>
                          <button
                            type="button"
                            disabled={busy || !channel.enabled}
                            onClick={() => management.test(channel)}
                          >
                            {busy ? <ReloadIcon className="managed-resource-spin" /> : null}
                            {t('settings.channels.test')}
                          </button>
                          <button
                            type="button"
                            aria-label={t('settings.channels.editNamed', { name: channel.name })}
                            disabled={busy}
                            onClick={() => management.openEdit(channel)}
                          >
                            <Pencil2Icon />
                          </button>
                          {deleting ? (
                            <>
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => setConfirmDeleteId(null)}
                              >
                                {t('common.cancel')}
                              </button>
                              <button
                                type="button"
                                className="danger"
                                disabled={busy}
                                onClick={() => {
                                  setConfirmDeleteId(null);
                                  management.remove(channel);
                                }}
                              >
                                {t('settings.channels.confirmDelete')}
                              </button>
                            </>
                          ) : (
                            <button
                              type="button"
                              className="danger-ghost"
                              aria-label={t('settings.channels.deleteNamed', { name: channel.name })}
                              disabled={busy}
                              onClick={() => setConfirmDeleteId(channel.id)}
                            >
                              <TrashIcon />
                            </button>
                          )}
                        </div>
                      </article>
                    );
                  })}
                </div>
              )}
            </div>
            <footer className="plugin-management-footer">
              <button type="button" className="secondary" onClick={() => void management.reload()}>
                <ReloadIcon /> {t('common.refresh')}
              </button>
              <button type="button" className="secondary" onClick={management.close}>
                {t('common.close')}
              </button>
            </footer>
          </>
        )}
      </section>
    </div>
  );
}

function ChannelConnectionEditor({
  management,
}: {
  management: ReturnType<typeof useChannelConnectionManagement>;
}) {
  const { t } = useI18n();
  const editor = management.editor;
  if (!editor) return null;
  const fields = useMemo(() => channelConnectionFields(editor.schema), [editor.schema]);
  const [draft, setDraft] = useState<ChannelConnectionDraft>(() =>
    channelConnectionDraftFrom(editor.schema, editor.config),
  );
  const [errors, setErrors] = useState<ChannelConnectionErrors>({});
  const nameRef = useRef<HTMLInputElement>(null);

  const update = (name: string, value: unknown) => {
    setDraft((current) => ({
      ...current,
      values: name === 'name' ? current.values : { ...current.values, [name]: value },
      ...(name === 'name' ? { name: String(value) } : {}),
    }));
    setErrors((current) => {
      if (!current[name]) return current;
      const next = { ...current };
      delete next[name];
      return next;
    });
  };
  const submit = () => {
    const nextErrors = validateChannelConnectionDraft(editor.schema, draft, Boolean(editor.config));
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length === 0) {
      void management.save(
        channelConnectionMutationFromDraft(editor.schema, draft, Boolean(editor.config)),
      );
    }
  };

  return (
    <>
      <div className="plugin-management-body channel-editor-body">
        <div className="channel-editor-basics">
          {!editor.config ? (
            <label>
              <span>{t('settings.channels.type')} *</span>
              <select
                value={draft.channelType}
                disabled={management.busyId !== null || editor.loading}
                onChange={(event) => management.changeType(event.target.value)}
              >
                {management.catalog
                  .filter((item) => item.enabled && item.discovered)
                  .map((item) => (
                    <option key={item.channel_type} value={item.channel_type}>
                      {item.channel_type}
                    </option>
                  ))}
              </select>
            </label>
          ) : null}
          <label className={errors.name ? 'invalid' : ''}>
            <span>{t('settings.channels.name')} *</span>
            <input
              ref={nameRef}
              value={draft.name}
              disabled={management.busyId !== null}
              onChange={(event) => update('name', event.target.value)}
            />
            {errors.name ? <em role="alert">{t('settings.channels.error.required')}</em> : null}
          </label>
          <label>
            <span>{t('settings.channels.descriptionField')}</span>
            <input
              value={draft.description}
              disabled={management.busyId !== null}
              onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))}
            />
          </label>
          <label className="plugin-config-checkbox">
            <input
              type="checkbox"
              checked={draft.enabled}
              disabled={management.busyId !== null}
              onChange={(event) => setDraft((current) => ({ ...current, enabled: event.target.checked }))}
            />
            <span>{t('settings.channels.enabled')}</span>
          </label>
        </div>
        {editor.loading ? (
          <div className="plugin-management-state">
            <ReloadIcon className="managed-resource-spin" />
          </div>
        ) : (
          <div className="plugin-config-fields channel-dynamic-fields">
            {fields.map((field) => (
              <ChannelField
                key={field.name}
                field={field}
                value={draft.values[field.name]}
                error={errors[field.name]}
                editing={Boolean(editor.config)}
                disabled={management.busyId !== null}
                onChange={(value) => update(field.name, value)}
              />
            ))}
          </div>
        )}
        {management.error ? <div className="plugin-management-error">{management.error}</div> : null}
      </div>
      <footer className="plugin-management-footer">
        <button type="button" className="secondary" disabled={management.busyId !== null} onClick={management.closeEditor}>
          {t('common.cancel')}
        </button>
        <button type="button" className="primary" disabled={management.busyId !== null || editor.loading} onClick={submit}>
          {management.busyId !== null ? <ReloadIcon className="managed-resource-spin" /> : null}
          {editor.config ? t('common.save') : t('common.create')}
        </button>
      </footer>
    </>
  );
}

function ChannelField({
  field,
  value,
  error,
  editing,
  disabled,
  onChange,
}: {
  field: ChannelConnectionField;
  value: unknown;
  error: string | undefined;
  editing: boolean;
  disabled: boolean;
  onChange: (value: unknown) => void;
}) {
  const { t } = useI18n();
  if (field.kind === 'boolean') {
    return (
      <label className="plugin-config-checkbox">
        <input type="checkbox" checked={value === true} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
        <span>{field.label}</span>
      </label>
    );
  }
  return (
    <label className={error ? 'invalid' : ''}>
      <span>{field.label} {field.required && !(editing && field.kind === 'secret') ? <b>*</b> : null}</span>
      {field.kind === 'select' ? (
        <select value={String(value ?? '')} disabled={disabled} onChange={(event) => onChange(field.options.find((option) => String(option) === event.target.value) ?? event.target.value)}>
          <option value="">{t('settings.channels.selectOption')}</option>
          {field.options.map((option) => <option key={String(option)} value={String(option)}>{String(option)}</option>)}
        </select>
      ) : (
        <input
          type={field.kind === 'secret' ? 'password' : field.kind === 'text' ? 'text' : 'number'}
          value={typeof value === 'string' || typeof value === 'number' ? value : ''}
          min={field.minimum ?? undefined}
          max={field.maximum ?? undefined}
          step={field.kind === 'integer' ? 1 : field.kind === 'number' ? 'any' : undefined}
          placeholder={field.kind === 'secret' && editing ? t('settings.channels.secretPlaceholder') : field.placeholder}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      {field.help ? <small>{field.help}</small> : null}
      {error ? <em role="alert">{t(`settings.channels.error.${error}`)}</em> : null}
    </label>
  );
}
