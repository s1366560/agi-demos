import { useEffect, useRef, useState } from 'react';
import {
  ClockIcon,
  Cross2Icon,
  ExclamationTriangleIcon,
  FileIcon,
  ReloadIcon,
  UploadIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  ManagedSkill,
  ManagedSkillVersion,
  ManagedSkillVersionDetail,
  ProjectSummary,
} from '../../types';
import type { SkillImportSubmission } from './useSkillPackageManagement';
import { useModalDialog } from './useModalDialog';

import './AgentDefinitionEditorDialog.css';
import './SkillPackageDialogs.css';

export function SkillImportDialog({
  projects,
  initialProjectId,
  allowTenantScope,
  busy,
  error,
  onClose,
  onImport,
}: {
  projects: ProjectSummary[];
  initialProjectId: string | null;
  allowTenantScope: boolean;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onImport: (submission: SkillImportSubmission) => void;
}) {
  const { t } = useI18n();
  const projectDefault = initialProjectId || projects[0]?.id || '';
  const [scope, setScope] = useState<'tenant' | 'project'>(
    allowTenantScope && !projectDefault ? 'tenant' : 'project'
  );
  const [projectId, setProjectId] = useState(projectDefault);
  const [archive, setArchive] = useState<File | null>(null);
  const [content, setContent] = useState('');
  const [overwrite, setOverwrite] = useState(false);
  const [changeSummary, setChangeSummary] = useState('');
  const [validationError, setValidationError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useModalDialog({
    active: true,
    initialFocusRef: fileInputRef,
    nested: true,
    onClose,
  });

  const submit = () => {
    if (!archive && !content.trim()) {
      setValidationError(t('settings.skillPackages.contentRequired'));
      return;
    }
    if (scope === 'project' && !projectId) {
      setValidationError(t('settings.skillPackages.projectRequired'));
      return;
    }
    setValidationError(null);
    onImport({
      archive,
      package: {
        skill_md_content: content.trim(),
        scope,
        project_id: scope === 'project' ? projectId : null,
        overwrite,
        change_summary: changeSummary.trim() || null,
      },
    });
  };

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
        className="agent-definition-dialog skill-package-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={t('settings.skillPackages.importTitle')}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="agent-definition-dialog-heading">
          <div className="agent-definition-dialog-icon skill-package-dialog-icon">
            <UploadIcon />
          </div>
          <div>
            <span>{t('settings.skillsEyebrow')}</span>
            <h2>{t('settings.skillPackages.importTitle')}</h2>
            <p>{t('settings.skillPackages.importDescription')}</p>
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

        <div className="agent-definition-dialog-body skill-package-import-body">
          <label className="skill-package-archive-picker">
            <span className="skill-package-archive-icon">
              <FileIcon />
            </span>
            <span>
              <strong>{archive?.name || t('settings.skillPackages.zipPlaceholder')}</strong>
              <small>{t('settings.skillPackages.zipDescription')}</small>
            </span>
            <em>{t('settings.skillPackages.chooseZip')}</em>
            <input
              ref={fileInputRef}
              type="file"
              accept=".zip,application/zip"
              disabled={busy}
              onChange={(event) => {
                const file = event.target.files?.[0] ?? null;
                setArchive(file);
                if (file) setContent('');
                setValidationError(null);
              }}
            />
          </label>

          <div className="skill-package-divider">
            <span>{t('settings.skillPackages.orPaste')}</span>
          </div>

          <label className="agent-definition-field">
            <span>{t('settings.skillPackages.skillMd')}</span>
            <textarea
              className="skill-package-code"
              rows={11}
              value={content}
              disabled={busy || archive !== null}
              placeholder={'---\nname: release-readiness\ndescription: Verify release evidence\n---'}
              onChange={(event) => {
                setContent(event.target.value);
                setValidationError(null);
              }}
            />
          </label>

          <div className="skill-package-import-options">
            <label className="agent-definition-field">
              <span>{t('settings.skillPackages.scope')}</span>
              <select
                value={scope}
                disabled={busy}
                onChange={(event) => {
                  const nextScope = event.target.value as 'tenant' | 'project';
                  setScope(nextScope);
                  if (nextScope === 'project' && !projectId) {
                    setProjectId(projects[0]?.id ?? '');
                  }
                }}
              >
                {allowTenantScope ? (
                  <option value="tenant">{t('settings.skillEditor.tenantScope')}</option>
                ) : null}
                <option value="project" disabled={projects.length === 0}>
                  {t('settings.skillPackages.projectScope')}
                </option>
              </select>
            </label>
            <label className="agent-definition-field">
              <span>{t('settings.skillPackages.project')}</span>
              <select
                value={projectId}
                disabled={busy || scope !== 'project'}
                onChange={(event) => setProjectId(event.target.value)}
              >
                <option value="">{t('settings.skillPackages.selectProject')}</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="agent-definition-field wide">
              <span>{t('settings.skillPackages.changeSummary')}</span>
              <input
                value={changeSummary}
                disabled={busy}
                maxLength={2000}
                onChange={(event) => setChangeSummary(event.target.value)}
              />
            </label>
            <label className="skill-package-checkbox wide">
              <input
                type="checkbox"
                checked={overwrite}
                disabled={busy}
                onChange={(event) => setOverwrite(event.target.checked)}
              />
              <span>
                <strong>{t('settings.skillPackages.overwrite')}</strong>
                <small>{t('settings.skillPackages.overwriteDescription')}</small>
              </span>
            </label>
          </div>
        </div>

        {validationError || error ? (
          <div className="agent-definition-dialog-error" role="alert">
            <ExclamationTriangleIcon />
            <span>{validationError || error}</span>
          </div>
        ) : null}

        <footer className="agent-definition-dialog-footer">
          <div />
          <div>
            <button type="button" disabled={busy} onClick={onClose}>
              {t('common.cancel')}
            </button>
            <button type="button" className="primary" disabled={busy} onClick={submit}>
              {busy ? <ReloadIcon className="managed-resource-spin" /> : <UploadIcon />}
              {t('settings.skillPackages.importAction')}
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}

export function SkillVersionsDialog({
  skill,
  versions,
  loading,
  rollbackVersion,
  preview,
  previewLoading,
  canRollback,
  error,
  onClose,
  onRollback,
  onPreview,
  onClosePreview,
}: {
  skill: ManagedSkill;
  versions: ManagedSkillVersion[];
  loading: boolean;
  rollbackVersion: number | null;
  preview: ManagedSkillVersionDetail | null;
  previewLoading: boolean;
  canRollback: boolean;
  error: string | null;
  onClose: () => void;
  onRollback: (versionNumber: number) => void;
  onPreview: (versionNumber: number) => void;
  onClosePreview: () => void;
}) {
  const { locale, t } = useI18n();
  const [confirmVersion, setConfirmVersion] = useState<number | null>(null);
  const dialogRef = useModalDialog({ active: true, nested: true, onClose });
  const busy = rollbackVersion !== null;

  useEffect(() => {
    if (rollbackVersion === null) setConfirmVersion(null);
  }, [rollbackVersion]);

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
        className="agent-definition-dialog skill-package-dialog skill-versions-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={t('settings.skillPackages.versionsTitle', { name: skill.name })}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="agent-definition-dialog-heading">
          <div className="agent-definition-dialog-icon skill-package-dialog-icon">
            <ClockIcon />
          </div>
          <div>
            <span>{t('settings.skillsEyebrow')}</span>
            <h2>{t('settings.skillPackages.versionsTitle', { name: skill.name })}</h2>
            <p>{t('settings.skillPackages.versionsDescription')}</p>
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

        <div className="agent-definition-dialog-body skill-version-list">
          {loading ? (
            <div className="skill-package-state">
              <ReloadIcon className="managed-resource-spin" />
              <span>{t('settings.skillPackages.loadingVersions')}</span>
            </div>
          ) : null}
          {!loading && versions.length === 0 ? (
            <div className="skill-package-state">
              <ClockIcon />
              <span>{t('settings.skillPackages.noVersions')}</span>
            </div>
          ) : null}
          {!loading
            ? versions.map((version) => {
                const current = version.version_number === skill.current_version;
                const confirming = confirmVersion === version.version_number;
                return (
                  <article className="skill-version-row" key={version.id}>
                    <div className="skill-version-number">
                      <strong>{version.version_label || `#${version.version_number}`}</strong>
                      <span>#{version.version_number}</span>
                    </div>
                    <div className="skill-version-copy">
                      <strong>
                        {version.change_summary || t('settings.skillPackages.noChangeSummary')}
                      </strong>
                      <span>
                        {t('settings.skillPackages.versionCreatedBy', {
                          author: version.created_by,
                          date: formatVersionDate(version.created_at, locale),
                        })}
                      </span>
                    </div>
                    <div className="skill-version-action">
                      <button
                        type="button"
                        className="skill-version-rollback"
                        disabled={busy || previewLoading}
                        onClick={() => onPreview(version.version_number)}
                      >
                        {t('settings.skillPackages.previewVersion')}
                      </button>
                      {current ? (
                        <span className="skill-version-current">
                          {t('settings.skillPackages.current')}
                        </span>
                      ) : confirming ? (
                        <div className="skill-version-confirmation">
                          <span>{t('settings.skillPackages.rollbackConfirm')}</span>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => setConfirmVersion(null)}
                          >
                            {t('common.cancel')}
                          </button>
                          <button
                            type="button"
                            className="danger"
                            disabled={busy}
                            onClick={() => onRollback(version.version_number)}
                          >
                            {rollbackVersion === version.version_number ? (
                              <ReloadIcon className="managed-resource-spin" />
                            ) : null}
                            {t('settings.skillPackages.rollback')}
                          </button>
                        </div>
                      ) : canRollback ? (
                        <button
                          type="button"
                          className="skill-version-rollback"
                          disabled={busy}
                          onClick={() => setConfirmVersion(version.version_number)}
                        >
                          {t('settings.skillPackages.rollback')}
                        </button>
                      ) : null}
                    </div>
                  </article>
                );
              })
            : null}
          {previewLoading ? (
            <div className="skill-version-preview skill-package-state">
              <ReloadIcon className="managed-resource-spin" />
              <span>{t('settings.skillPackages.loadingPreview')}</span>
            </div>
          ) : null}
          {preview ? (
            <section className="skill-version-preview">
              <header>
                <div>
                  <strong>
                    {t('settings.skillPackages.previewTitle', {
                      version: preview.version_label || `#${preview.version_number}`,
                    })}
                  </strong>
                  <span>
                    {t('settings.skillPackages.resourceCount', {
                      count: Object.keys(preview.resource_files ?? {}).length,
                    })}
                  </span>
                </div>
                <button type="button" onClick={onClosePreview}>
                  {t('common.close')}
                </button>
              </header>
              <pre>{preview.skill_md_content}</pre>
            </section>
          ) : null}
        </div>

        {error ? (
          <div className="agent-definition-dialog-error" role="alert">
            <ExclamationTriangleIcon />
            <span>{error}</span>
          </div>
        ) : null}

        <footer className="agent-definition-dialog-footer">
          <div />
          <div>
            <button type="button" disabled={busy} onClick={onClose}>
              {t('common.close')}
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}

function formatVersionDate(value: string, locale: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}
