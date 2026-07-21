import { useRef, useState, type ReactNode } from 'react';
import {
  Cross2Icon,
  ExclamationTriangleIcon,
  PersonIcon,
  ReloadIcon,
  TrashIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { ManagedSubAgent, ManagedSubAgentMutation, ProjectSummary } from '../../types';
import {
  subAgentDraftFrom,
  subAgentMutationFromDraft,
  validateSubAgentDraft,
  type SubAgentDraftErrors,
  type SubAgentEditorDraft,
} from './subAgentEditorModel';
import { useModalDialog } from './useModalDialog';

import './AgentDefinitionEditorDialog.css';

type EditorTab = 'identity' | 'trigger' | 'runtime' | 'capabilities';

export function SubAgentEditorDialog({
  definition,
  projects,
  initialProjectId,
  busy,
  error,
  onClose,
  onSave,
  onDelete,
}: {
  definition: ManagedSubAgent | null;
  projects: ProjectSummary[];
  initialProjectId: string | null;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSave: (input: ManagedSubAgentMutation) => void;
  onDelete: (() => void) | null;
}) {
  const { t } = useI18n();
  const [draft, setDraft] = useState<SubAgentEditorDraft>(() =>
    subAgentDraftFrom(definition, initialProjectId),
  );
  const [errors, setErrors] = useState<SubAgentDraftErrors>({});
  const [activeTab, setActiveTab] = useState<EditorTab>('identity');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const firstInputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useModalDialog({
    active: true,
    initialFocusRef: firstInputRef,
    nested: true,
    onClose,
  });

  const update = <K extends keyof SubAgentEditorDraft>(
    key: K,
    value: SubAgentEditorDraft[K],
  ) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setErrors((current) => {
      if (!current[key]) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  };

  const submit = () => {
    const nextErrors = validateSubAgentDraft(draft);
    setErrors(nextErrors);
    const firstError = Object.keys(nextErrors)[0] as keyof SubAgentEditorDraft | undefined;
    if (firstError) {
      setActiveTab(tabForField(firstError));
      return;
    }
    onSave(subAgentMutationFromDraft(draft));
  };

  const tabs: Array<{ id: EditorTab; label: string }> = [
    { id: 'identity', label: t('settings.subagentEditor.identity') },
    { id: 'trigger', label: t('settings.subagentEditor.trigger') },
    { id: 'runtime', label: t('settings.subagentEditor.runtime') },
    { id: 'capabilities', label: t('settings.subagentEditor.capabilities') },
  ];

  return (
    <div
      className="agent-definition-dialog-backdrop"
      role="presentation"
      onMouseDown={() => {
        if (!busy) onClose();
      }}
    >
      <section
        ref={dialogRef}
        className="agent-definition-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={t(
          definition
            ? 'settings.subagentEditor.editTitle'
            : 'settings.subagentEditor.createTitle',
        )}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="agent-definition-dialog-heading">
          <div className="agent-definition-dialog-icon">
            <PersonIcon />
          </div>
          <div>
            <span>{t('settings.subagentsEyebrow')}</span>
            <h2>
              {t(
                definition
                  ? 'settings.subagentEditor.editTitle'
                  : 'settings.subagentEditor.createTitle',
              )}
            </h2>
            <p>{t('settings.subagentEditor.description')}</p>
          </div>
          <button
            type="button"
            className="agent-definition-dialog-close"
            aria-label={t('common.close')}
            disabled={busy}
            onClick={onClose}
          >
            <Cross2Icon />
          </button>
        </header>

        <nav
          className="agent-definition-dialog-tabs"
          aria-label={t('settings.subagentEditor.tabs')}
        >
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={activeTab === tab.id ? 'active' : ''}
              aria-pressed={activeTab === tab.id}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        <div className="agent-definition-dialog-body">
          {activeTab === 'identity' ? (
            <div className="agent-definition-form-grid">
              <Field label={t('settings.subagentEditor.name')} error={fieldError(errors.name, t)}>
                <input
                  ref={firstInputRef}
                  value={draft.name}
                  disabled={busy || Boolean(definition)}
                  placeholder="release_reviewer"
                  onChange={(event) => update('name', event.target.value)}
                />
              </Field>
              <Field
                label={t('settings.subagentEditor.displayName')}
                error={fieldError(errors.displayName, t)}
              >
                <input
                  value={draft.displayName}
                  disabled={busy}
                  onChange={(event) => update('displayName', event.target.value)}
                />
              </Field>
              <Field label={t('settings.subagentEditor.scope')}>
                <select
                  value={draft.scopeId}
                  disabled={busy || Boolean(definition)}
                  onChange={(event) => update('scopeId', event.target.value)}
                >
                  <option value="">{t('settings.subagentEditor.tenantScope')}</option>
                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={t('settings.subagentEditor.color')}>
                <input
                  value={draft.color}
                  disabled={busy}
                  placeholder="blue"
                  onChange={(event) => update('color', event.target.value)}
                />
              </Field>
              <Field
                className="wide"
                label={t('settings.subagentEditor.systemPrompt')}
                error={fieldError(errors.systemPrompt, t)}
              >
                <textarea
                  rows={8}
                  value={draft.systemPrompt}
                  disabled={busy}
                  onChange={(event) => update('systemPrompt', event.target.value)}
                />
              </Field>
            </div>
          ) : null}

          {activeTab === 'trigger' ? (
            <div className="agent-definition-form-grid">
              <Field
                className="wide"
                label={t('settings.subagentEditor.triggerDescription')}
                error={fieldError(errors.triggerDescription, t)}
              >
                <textarea
                  rows={4}
                  value={draft.triggerDescription}
                  disabled={busy}
                  onChange={(event) => update('triggerDescription', event.target.value)}
                />
              </Field>
              <ListField
                label={t('settings.subagentEditor.triggerKeywords')}
                value={draft.triggerKeywords}
                disabled={busy}
                onChange={(value) => update('triggerKeywords', value)}
              />
              <ListField
                label={t('settings.subagentEditor.triggerExamples')}
                value={draft.triggerExamples}
                disabled={busy}
                onChange={(value) => update('triggerExamples', value)}
              />
            </div>
          ) : null}

          {activeTab === 'runtime' ? (
            <div className="agent-definition-form-grid">
              <Field label={t('settings.subagentEditor.model')}>
                <input
                  value={draft.model}
                  disabled={busy}
                  placeholder="inherit"
                  onChange={(event) => update('model', event.target.value)}
                />
              </Field>
              <NumberField
                label={t('settings.subagentEditor.temperature')}
                value={draft.temperature}
                min={0}
                max={2}
                step={0.1}
                disabled={busy}
                error={fieldError(errors.temperature, t)}
                onChange={(value) => update('temperature', value)}
              />
              <NumberField
                label={t('settings.subagentEditor.maxTokens')}
                value={draft.maxTokens}
                min={1}
                max={32768}
                step={1}
                disabled={busy}
                error={fieldError(errors.maxTokens, t)}
                onChange={(value) => update('maxTokens', value)}
              />
              <NumberField
                label={t('settings.subagentEditor.maxIterations')}
                value={draft.maxIterations}
                min={1}
                max={50}
                step={1}
                disabled={busy}
                error={fieldError(errors.maxIterations, t)}
                onChange={(value) => update('maxIterations', value)}
              />
            </div>
          ) : null}

          {activeTab === 'capabilities' ? (
            <div className="agent-definition-form-grid">
              <ListField
                className="wide"
                label={t('settings.subagentEditor.allowedTools')}
                value={draft.allowedTools}
                disabled={busy}
                onChange={(value) => update('allowedTools', value)}
              />
              <ListField
                label={t('settings.subagentEditor.allowedSkills')}
                value={draft.allowedSkills}
                disabled={busy}
                onChange={(value) => update('allowedSkills', value)}
              />
              <ListField
                label={t('settings.subagentEditor.allowedMcpServers')}
                value={draft.allowedMcpServers}
                disabled={busy}
                onChange={(value) => update('allowedMcpServers', value)}
              />
            </div>
          ) : null}
        </div>

        {error ? (
          <div className="agent-definition-dialog-error" role="alert">
            <ExclamationTriangleIcon />
            <span>{error}</span>
          </div>
        ) : null}

        <footer className="agent-definition-dialog-footer">
          <div>
            {definition && onDelete ? (
              confirmDelete ? (
                <div className="agent-definition-delete-confirmation">
                  <span>{t('settings.subagentEditor.deleteConfirm')}</span>
                  <button type="button" disabled={busy} onClick={() => setConfirmDelete(false)}>
                    {t('common.cancel')}
                  </button>
                  <button type="button" className="danger" disabled={busy} onClick={onDelete}>
                    <TrashIcon /> {t('settings.subagentEditor.delete')}
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  className="agent-definition-delete"
                  disabled={busy}
                  onClick={() => setConfirmDelete(true)}
                >
                  <TrashIcon /> {t('settings.subagentEditor.delete')}
                </button>
              )
            ) : null}
          </div>
          <div>
            <button type="button" disabled={busy} onClick={onClose}>
              {t('common.cancel')}
            </button>
            <button type="button" className="primary" disabled={busy} onClick={submit}>
              {busy ? <ReloadIcon className="managed-resource-spin" /> : null}
              {t(definition ? 'common.save' : 'settings.subagentEditor.createAction')}
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}

function Field({
  label,
  error,
  className = '',
  children,
}: {
  label: string;
  error?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <label className={`agent-definition-field ${className}`}>
      <span>{label}</span>
      {children}
      {error ? <small>{error}</small> : null}
    </label>
  );
}

function ListField({
  label,
  value,
  disabled,
  className = '',
  onChange,
}: {
  label: string;
  value: string;
  disabled: boolean;
  className?: string;
  onChange: (value: string) => void;
}) {
  return (
    <Field label={label} className={className}>
      <textarea
        rows={6}
        value={value}
        disabled={disabled}
        placeholder={label}
        onChange={(event) => onChange(event.target.value)}
      />
    </Field>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  step,
  disabled,
  error,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  disabled: boolean;
  error?: string;
  onChange: (value: number) => void;
}) {
  return (
    <Field label={label} error={error}>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </Field>
  );
}

function fieldError(
  error: SubAgentDraftErrors[keyof SubAgentDraftErrors],
  t: (key: string) => string,
): string | undefined {
  return error ? t(`settings.subagentEditor.error.${error}`) : undefined;
}

function tabForField(field: keyof SubAgentEditorDraft): EditorTab {
  if (
    field === 'triggerDescription' ||
    field === 'triggerKeywords' ||
    field === 'triggerExamples'
  ) {
    return 'trigger';
  }
  if (
    field === 'model' ||
    field === 'temperature' ||
    field === 'maxTokens' ||
    field === 'maxIterations'
  ) {
    return 'runtime';
  }
  if (field === 'allowedTools' || field === 'allowedSkills' || field === 'allowedMcpServers') {
    return 'capabilities';
  }
  return 'identity';
}
