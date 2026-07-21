import { useMemo, useRef, useState } from 'react';
import {
  CheckCircledIcon,
  ComponentInstanceIcon,
  Cross2Icon,
  ExclamationTriangleIcon,
  ReloadIcon,
  TrashIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  ManagedPlugin,
  PluginActionDetails,
  PluginConfigRecord,
  PluginConfigSchema,
  UpdatePluginConfigRequest,
} from '../../types';
import {
  pluginConfigDraftFrom,
  pluginConfigFields,
  pluginConfigMutationFromDraft,
  pluginCapabilityCountEntries,
  validatePluginConfigDraft,
  validatePluginRequirement,
  type PluginActionTimelineEntry,
  type PluginConfigDraft,
  type PluginConfigErrors,
  type PluginConfigField,
} from './pluginManagementModel';
import type { usePluginManagement } from './usePluginManagement';
import { useModalDialog } from './useModalDialog';

import './PluginManagementDialogs.css';

export function PluginInstallDialog({
  busy,
  error,
  onClose,
  onInstall,
}: {
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onInstall: (requirement: string) => void;
}) {
  const { t } = useI18n();
  const [requirement, setRequirement] = useState('');
  const [requiredError, setRequiredError] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useModalDialog({
    active: true,
    initialFocusRef: inputRef,
    nested: true,
    onClose,
  });

  const submit = () => {
    const invalid = validatePluginRequirement(requirement) !== null;
    setRequiredError(invalid);
    if (!invalid) onInstall(requirement.trim());
  };

  return (
    <DialogFrame
      dialogRef={dialogRef}
      title={t('settings.pluginManager.installTitle')}
      description={t('settings.pluginManager.installDescription')}
      busy={busy}
      onClose={onClose}
    >
      <div className="plugin-management-body compact">
        <label className={requiredError ? 'invalid' : ''}>
          <span>{t('settings.pluginManager.requirement')}</span>
          <input
            ref={inputRef}
            value={requirement}
            onChange={(event) => {
              setRequirement(event.target.value);
              if (requiredError) setRequiredError(false);
            }}
            placeholder={t('settings.pluginManager.requirementPlaceholder')}
            aria-invalid={requiredError}
          />
          <small>{t('settings.pluginManager.requirementHelp')}</small>
          {requiredError ? (
            <em role="alert">{t('settings.pluginManager.error.required')}</em>
          ) : null}
        </label>
        <DialogError error={error} />
      </div>
      <footer className="plugin-management-footer">
        <button type="button" className="secondary" disabled={busy} onClick={onClose}>
          {t('common.cancel')}
        </button>
        <button type="button" className="primary" disabled={busy} onClick={submit}>
          {busy ? <ReloadIcon className="managed-resource-spin" /> : <ComponentInstanceIcon />}
          {t('settings.pluginManager.install')}
        </button>
      </footer>
    </DialogFrame>
  );
}

export function PluginConfigDialog({
  plugin,
  schema,
  record,
  loading,
  busy,
  error,
  initialConfirmUninstall = false,
  onClose,
  onSave,
  onUninstall,
}: {
  plugin: ManagedPlugin;
  schema: PluginConfigSchema | null;
  record: PluginConfigRecord | null;
  loading: boolean;
  busy: boolean;
  error: string | null;
  initialConfirmUninstall?: boolean;
  onClose: () => void;
  onSave: (input: UpdatePluginConfigRequest) => void;
  onUninstall: () => void;
}) {
  const { t } = useI18n();
  const fields = useMemo(() => (schema ? pluginConfigFields(schema) : []), [schema]);
  const [draft, setDraft] = useState<PluginConfigDraft>(() =>
    schema ? pluginConfigDraftFrom(schema, record) : {},
  );
  const [errors, setErrors] = useState<PluginConfigErrors>({});
  const [confirmUninstall, setConfirmUninstall] = useState(initialConfirmUninstall);
  const dialogRef = useModalDialog({ active: true, nested: true, onClose });

  const update = (name: string, value: unknown) => {
    setDraft((current) => ({ ...current, [name]: value }));
    setErrors((current) => {
      if (!current[name]) return current;
      const next = { ...current };
      delete next[name];
      return next;
    });
  };

  const submit = () => {
    if (!schema) return;
    const nextErrors = validatePluginConfigDraft(schema, draft);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length === 0) {
      onSave(pluginConfigMutationFromDraft(schema, draft));
    }
  };

  return (
    <DialogFrame
      dialogRef={dialogRef}
      title={t('settings.pluginManager.configureTitle', { name: plugin.name })}
      description={t('settings.pluginManager.configureDescription')}
      busy={busy}
      onClose={onClose}
    >
      <div className="plugin-management-body">
        {loading ? (
          <div className="plugin-management-state">
            <ReloadIcon className="managed-resource-spin" />
            <span>{t('settings.pluginManager.loadingConfig')}</span>
          </div>
        ) : schema?.schema_supported ? (
          fields.length > 0 ? (
            <div className="plugin-config-fields">
              {fields.map((field) => (
                <PluginConfigInput
                  key={field.name}
                  field={field}
                  value={draft[field.name]}
                  error={errors[field.name]}
                  disabled={busy}
                  onChange={(value) => update(field.name, value)}
                />
              ))}
            </div>
          ) : (
            <div className="plugin-management-state">
              <ComponentInstanceIcon />
              <span>{t('settings.pluginManager.noFields')}</span>
            </div>
          )
        ) : (
          <div className="plugin-management-state">
            <ExclamationTriangleIcon />
            <span>{t('settings.pluginManager.unsupportedConfig')}</span>
          </div>
        )}
        <DialogError error={error} />
      </div>
      <footer className="plugin-management-footer split">
        <div>
          {confirmUninstall ? (
            <>
              <span>{t('settings.pluginManager.uninstallConfirmation')}</span>
              <button type="button" className="secondary" disabled={busy} onClick={() => setConfirmUninstall(false)}>
                {t('common.cancel')}
              </button>
              <button type="button" className="danger" disabled={busy} onClick={onUninstall}>
                <TrashIcon /> {t('settings.pluginManager.confirmUninstall')}
              </button>
            </>
          ) : (
            <button type="button" className="danger-ghost" disabled={busy} onClick={() => setConfirmUninstall(true)}>
              <TrashIcon /> {t('settings.pluginManager.uninstall')}
            </button>
          )}
        </div>
        <div>
          <button type="button" className="secondary" disabled={busy} onClick={onClose}>
            {t('common.cancel')}
          </button>
          <button
            type="button"
            className="primary"
            disabled={busy || loading || !schema?.schema_supported}
            onClick={submit}
          >
            {busy ? <ReloadIcon className="managed-resource-spin" /> : <ComponentInstanceIcon />}
            {t('common.save')}
          </button>
        </div>
      </footer>
    </DialogFrame>
  );
}

export function PluginRuntimeActivityDialog({
  management,
}: {
  management: ReturnType<typeof usePluginManagement>;
}) {
  const { locale, t } = useI18n();
  const dialogRef = useModalDialog({
    active: management.activityOpen,
    nested: true,
    onClose: management.closeActivity,
  });
  if (!management.activityOpen) return null;

  const trace = management.lastActionDetails?.control_plane_trace;
  return (
    <DialogFrame
      dialogRef={dialogRef}
      title={t('settings.pluginActivity.title')}
      description={t('settings.pluginActivity.description')}
      busy={management.activityLoading}
      onClose={management.closeActivity}
    >
      <div className="plugin-management-body plugin-activity-body">
        <div className="plugin-activity-toolbar">
          <span>{t('settings.pluginActivity.sessionNote')}</span>
          <button
            type="button"
            disabled={management.activityLoading}
            onClick={() => void management.refreshActivity()}
          >
            <ReloadIcon className={management.activityLoading ? 'managed-resource-spin' : ''} />
            {t('settings.pluginActivity.refresh')}
          </button>
        </div>
        <DialogError error={management.activityError} />
        {trace ? (
          <ActivitySection title={t('settings.pluginActivity.latestTrace')}>
            <div className="plugin-activity-trace">
              <strong>{trace.action}</strong>
              <code>{trace.trace_id}</code>
              <span>{new Date(trace.timestamp).toLocaleString(locale)}</span>
            </div>
            <CapabilityCounts details={management.lastActionDetails} />
          </ActivitySection>
        ) : null}
        <ActivitySection title={t('settings.pluginActivity.diagnostics')}>
          {management.activityLoading && management.diagnostics.length === 0 ? (
            <div className="plugin-management-state compact">
              <ReloadIcon className="managed-resource-spin" />
              <span>{t('settings.pluginActivity.loading')}</span>
            </div>
          ) : management.diagnostics.length > 0 ? (
            <div className="plugin-activity-diagnostics">
              {management.diagnostics.map((diagnostic, index) => (
                <article key={`${diagnostic.plugin_name}:${diagnostic.code}:${index}`}>
                  <span data-level={diagnostic.level}>{diagnostic.level}</span>
                  <div>
                    <strong>{diagnostic.plugin_name || t('settings.pluginActivity.runtime')}</strong>
                    <code>{diagnostic.code}</code>
                    <p>{diagnostic.message}</p>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <p className="plugin-activity-empty">{t('settings.pluginActivity.noDiagnostics')}</p>
          )}
        </ActivitySection>
        <ActivitySection title={t('settings.pluginActivity.timeline')}>
          {management.actionTimeline.length > 0 ? (
            <div className="plugin-activity-timeline">
              {management.actionTimeline.map((entry) => (
                <TimelineEntry key={entry.id} entry={entry} locale={locale} />
              ))}
            </div>
          ) : (
            <p className="plugin-activity-empty">{t('settings.pluginActivity.noTimeline')}</p>
          )}
        </ActivitySection>
      </div>
      <footer className="plugin-management-footer">
        <button type="button" className="secondary" onClick={management.closeActivity}>
          {t('common.close')}
        </button>
      </footer>
    </DialogFrame>
  );
}

function ActivitySection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="plugin-activity-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function CapabilityCounts({ details }: { details: PluginActionDetails | null }) {
  const { t } = useI18n();
  const counts = details?.control_plane_trace?.capability_counts;
  const reloadPlan = details?.channel_reload_plan;
  if (!counts && !reloadPlan) return null;
  return (
    <div className="plugin-activity-metrics">
      {counts
        ? pluginCapabilityCountEntries(counts).map(([key, value]) => (
            <span key={key}>
              <b>{value}</b> {t(`settings.pluginActivity.capability.${key}`)}
            </span>
          ))
        : null}
      {reloadPlan
        ? Object.entries(reloadPlan).map(([key, value]) => (
            <span key={key}>
              <b>{value}</b> {t('settings.pluginActivity.reloadMetric', { name: key })}
            </span>
          ))
        : null}
    </div>
  );
}

function TimelineEntry({
  entry,
  locale,
}: {
  entry: PluginActionTimelineEntry;
  locale: string;
}) {
  return (
    <article data-success={entry.success}>
      {entry.success ? <CheckCircledIcon /> : <ExclamationTriangleIcon />}
      <div>
        <strong>{entry.action}</strong>
        <span>{new Date(entry.timestamp).toLocaleString(locale)}</span>
        <p>{entry.message}</p>
        <code>{entry.id}</code>
        <CapabilityCounts details={entry.details} />
      </div>
    </article>
  );
}

function PluginConfigInput({
  field,
  value,
  error,
  disabled,
  onChange,
}: {
  field: PluginConfigField;
  value: unknown;
  error: string | undefined;
  disabled: boolean;
  onChange: (value: unknown) => void;
}) {
  const { t } = useI18n();
  const errorText = error ? t(`settings.pluginManager.error.${error}`) : null;
  if (field.kind === 'boolean') {
    return (
      <label className={`plugin-config-checkbox ${error ? 'invalid' : ''}`}>
        <input
          type="checkbox"
          checked={value === true}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span>{field.label}</span>
      </label>
    );
  }

  return (
    <label className={error ? 'invalid' : ''}>
      <span>
        {field.label} {field.required ? <b>*</b> : null}
      </span>
      {field.kind === 'select' ? (
        <select
          value={String(value ?? '')}
          disabled={disabled}
          onChange={(event) => {
            const option = field.options.find((candidate) => String(candidate) === event.target.value);
            onChange(option ?? event.target.value);
          }}
        >
          <option value="">{t('settings.pluginManager.selectOption')}</option>
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
            field.kind === 'secret'
              ? t('settings.pluginManager.secretPlaceholder')
              : field.placeholder
          }
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      {field.help ? <small>{field.help}</small> : null}
      {errorText ? <em role="alert">{errorText}</em> : null}
    </label>
  );
}

function DialogFrame({
  dialogRef,
  title,
  description,
  busy,
  onClose,
  children,
}: {
  dialogRef: React.RefObject<HTMLElement | null>;
  title: string;
  description: string;
  busy: boolean;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const { t } = useI18n();
  return (
    <div className="plugin-management-backdrop" role="presentation" onMouseDown={() => !busy && onClose()}>
      <section
        ref={dialogRef}
        className="plugin-management-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="plugin-management-heading">
          <ComponentInstanceIcon />
          <div>
            <span>{t('settings.pluginsEyebrow')}</span>
            <h2>{title}</h2>
            <p>{description}</p>
          </div>
          <button type="button" aria-label={t('common.close')} disabled={busy} onClick={onClose}>
            <Cross2Icon />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}

function DialogError({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div className="plugin-management-error" role="alert">
      <ExclamationTriangleIcon />
      <span>{error}</span>
    </div>
  );
}
