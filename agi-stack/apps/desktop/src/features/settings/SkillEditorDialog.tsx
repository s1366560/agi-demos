import { useRef, useState } from 'react';
import {
  Cross2Icon,
  ExclamationTriangleIcon,
  MagicWandIcon,
  ReloadIcon,
  TrashIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  ManagedSkill,
  ManagedSkillCreateMutation,
  ManagedSkillMutation,
  ProjectSummary,
} from '../../types';
import {
  skillCreateMutationFromDraft,
  skillDraftFrom,
  skillUpdateMutationFromDraft,
  validateSkillDraft,
  type SkillDraftErrors,
  type SkillDraftField,
  type SkillEditorDraft,
} from './skillEditorModel';
import { useModalDialog } from './useModalDialog';

import './AgentDefinitionEditorDialog.css';
import './SkillEditorDialog.css';

type EditorTab = 'package' | 'content' | 'advanced';

export function SkillEditorDialog({
  skill,
  projects,
  initialProjectId,
  allowTenantScope,
  loading,
  contentReady,
  busy,
  error,
  onClose,
  onSave,
  onDelete,
}: {
  skill: ManagedSkill | null;
  projects: ProjectSummary[];
  initialProjectId: string | null;
  allowTenantScope: boolean;
  loading: boolean;
  contentReady: boolean;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSave: (input: ManagedSkillCreateMutation | ManagedSkillMutation) => void;
  onDelete: (() => void) | null;
}) {
  const { t } = useI18n();
  const [draft, setDraft] = useState<SkillEditorDraft>(() =>
    skillDraftFrom(skill, initialProjectId)
  );
  const [errors, setErrors] = useState<SkillDraftErrors>({});
  const [activeTab, setActiveTab] = useState<EditorTab>('package');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const firstInputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useModalDialog({
    active: true,
    initialFocusRef: firstInputRef,
    nested: true,
    onClose,
  });
  const disabled = loading || busy;

  const update = <K extends keyof SkillEditorDraft>(key: K, value: SkillEditorDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setErrors((current) => {
      if (!current[key]) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  };

  const submit = () => {
    const nextErrors = validateSkillDraft(draft);
    setErrors(nextErrors);
    const firstError = Object.keys(nextErrors)[0] as SkillDraftField | undefined;
    if (firstError) {
      setActiveTab(tabForField(firstError));
      return;
    }
    onSave(skill ? skillUpdateMutationFromDraft(draft) : skillCreateMutationFromDraft(draft));
  };

  const tabs: Array<{ id: EditorTab; label: string }> = [
    { id: 'package', label: t('settings.skillEditor.package') },
    { id: 'content', label: t('settings.skillEditor.content') },
    { id: 'advanced', label: t('settings.skillEditor.advanced') },
  ];

  return (
    <div
      className="agent-definition-dialog-backdrop"
      role="presentation"
      onMouseDown={() => {
        if (!disabled) onClose();
      }}
    >
      <section
        ref={dialogRef}
        className="agent-definition-dialog skill-editor-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={t(
          skill ? 'settings.skillEditor.editTitle' : 'settings.skillEditor.createTitle'
        )}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="agent-definition-dialog-heading">
          <div className="agent-definition-dialog-icon skill-editor-icon">
            <MagicWandIcon />
          </div>
          <div>
            <span>{t('settings.skillsEyebrow')}</span>
            <h2>
              {t(skill ? 'settings.skillEditor.editTitle' : 'settings.skillEditor.createTitle')}
            </h2>
            <p>{t('settings.skillEditor.description')}</p>
          </div>
          <button
            type="button"
            className="agent-definition-dialog-close"
            aria-label={t('common.close')}
            disabled={disabled}
            onClick={onClose}
          >
            <Cross2Icon />
          </button>
        </header>

        <nav className="agent-definition-dialog-tabs" aria-label={t('settings.skillEditor.tabs')}>
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={activeTab === tab.id ? 'active' : ''}
              aria-pressed={activeTab === tab.id}
              disabled={loading}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        <div className="agent-definition-dialog-body">
          {loading ? (
            <div className="skill-editor-loading">
              <ReloadIcon className="managed-resource-spin" />
              <span>{t('settings.skillEditor.loading')}</span>
            </div>
          ) : null}
          {!loading && activeTab === 'package' ? (
            <div className="agent-definition-form-grid">
              <EditorField
                label={t('settings.skillEditor.name')}
                error={fieldError(errors, 'name', t)}
              >
                <input
                  ref={firstInputRef}
                  value={draft.name}
                  disabled={busy || Boolean(skill)}
                  placeholder="release-readiness"
                  onChange={(event) => update('name', event.target.value)}
                />
              </EditorField>
              <EditorField
                label={t('settings.skillEditor.scope')}
                error={fieldError(errors, 'projectId', t)}
              >
                <select
                  value={draft.scope === 'tenant' ? '' : draft.projectId}
                  disabled={busy || Boolean(skill)}
                  onChange={(event) => {
                    update('scope', event.target.value ? 'project' : 'tenant');
                    update('projectId', event.target.value);
                  }}
                >
                  {allowTenantScope ? (
                    <option value="">{t('settings.skillEditor.tenantScope')}</option>
                  ) : null}
                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </select>
              </EditorField>
              <EditorField
                className="wide"
                label={t('settings.skillEditor.descriptionLabel')}
                error={fieldError(errors, 'description', t)}
              >
                <textarea
                  rows={4}
                  value={draft.description}
                  disabled={busy}
                  onChange={(event) => update('description', event.target.value)}
                />
              </EditorField>
              <EditorField
                className="wide"
                label={t('settings.skillEditor.allowedTools')}
                error={fieldError(errors, 'allowedToolsRaw', t)}
              >
                <input
                  value={draft.allowedToolsRaw}
                  disabled={busy}
                  placeholder="read git_diff"
                  onChange={(event) => update('allowedToolsRaw', event.target.value)}
                />
              </EditorField>
            </div>
          ) : null}

          {!loading && activeTab === 'content' ? (
            <EditorField label={t('settings.skillEditor.skillBody')}>
              <textarea
                className="skill-editor-code"
                rows={19}
                value={draft.body}
                disabled={busy}
                onChange={(event) => update('body', event.target.value)}
              />
            </EditorField>
          ) : null}

          {!loading && activeTab === 'advanced' ? (
            <div className="agent-definition-form-grid">
              <EditorField
                label={t('settings.skillEditor.specVersion')}
                error={fieldError(errors, 'specVersion', t)}
              >
                <input
                  value={draft.specVersion}
                  disabled={busy}
                  onChange={(event) => update('specVersion', event.target.value)}
                />
              </EditorField>
              <EditorField
                label={t('settings.skillEditor.license')}
                error={fieldError(errors, 'license', t)}
              >
                <input
                  value={draft.license}
                  disabled={busy}
                  placeholder="MIT"
                  onChange={(event) => update('license', event.target.value)}
                />
              </EditorField>
              <EditorField
                className="wide"
                label={t('settings.skillEditor.compatibility')}
                error={fieldError(errors, 'compatibility', t)}
              >
                <textarea
                  rows={3}
                  value={draft.compatibility}
                  disabled={busy}
                  onChange={(event) => update('compatibility', event.target.value)}
                />
              </EditorField>
              <EditorField
                className="wide"
                label={t('settings.skillEditor.metadata')}
                error={fieldError(errors, 'metadata', t)}
              >
                <textarea
                  className="skill-editor-code"
                  rows={9}
                  value={draft.metadata}
                  disabled={busy}
                  onChange={(event) => update('metadata', event.target.value)}
                />
              </EditorField>
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
            {skill && onDelete ? (
              confirmDelete ? (
                <div className="agent-definition-delete-confirmation">
                  <span>{t('settings.skillEditor.deleteConfirmation')}</span>
                  <button type="button" disabled={disabled} onClick={() => setConfirmDelete(false)}>
                    {t('common.cancel')}
                  </button>
                  <button type="button" className="danger" disabled={disabled} onClick={onDelete}>
                    {t('settings.skillEditor.confirmDelete')}
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  className="agent-definition-delete"
                  disabled={disabled}
                  onClick={() => setConfirmDelete(true)}
                >
                  <TrashIcon /> {t('settings.skillEditor.delete')}
                </button>
              )
            ) : null}
          </div>
          <div>
            <button type="button" disabled={disabled} onClick={onClose}>
              {t('common.cancel')}
            </button>
            <button
              type="button"
              className="primary"
              disabled={disabled || !contentReady}
              onClick={submit}
            >
              {busy || loading ? (
                <ReloadIcon className="managed-resource-spin" />
              ) : (
                <MagicWandIcon />
              )}
              {t(skill ? 'common.save' : 'common.create')}
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}

function EditorField({
  label,
  error,
  className = '',
  children,
}: {
  label: string;
  error?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <label className={`agent-definition-field ${className}`.trim()}>
      <span>{label}</span>
      {children}
      {error ? <small role="alert">{error}</small> : null}
    </label>
  );
}

function fieldError(
  errors: SkillDraftErrors,
  field: SkillDraftField,
  t: (key: string) => string
): string | undefined {
  const error = errors[field];
  return error ? t(`settings.skillEditor.error.${error}`) : undefined;
}

function tabForField(field: SkillDraftField): EditorTab {
  if (field === 'body') return 'content';
  if (
    field === 'metadata' ||
    field === 'license' ||
    field === 'compatibility' ||
    field === 'specVersion'
  ) {
    return 'advanced';
  }
  return 'package';
}
