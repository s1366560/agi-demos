import { useRef } from 'react';
import {
  Cross2Icon,
  ExclamationTriangleIcon,
  PersonIcon,
  PlusIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { ManagedSubAgentTemplate } from '../../types';
import { useModalDialog } from './useModalDialog';

import './AgentDefinitionEditorDialog.css';
import './SubAgentLibraryDialog.css';

export function SubAgentLibraryDialog({
  templates,
  loading,
  busyId,
  error,
  onClose,
  onInstall,
}: {
  templates: ManagedSubAgentTemplate[];
  loading: boolean;
  busyId: string | null;
  error: string | null;
  onClose: () => void;
  onInstall: (template: ManagedSubAgentTemplate) => void;
}) {
  const { t } = useI18n();
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useModalDialog({
    active: true,
    initialFocusRef: closeButtonRef,
    nested: true,
    onClose,
  });

  return (
    <div
      className="agent-definition-dialog-backdrop"
      role="presentation"
      onMouseDown={() => {
        if (!busyId) onClose();
      }}
    >
      <section
        ref={dialogRef}
        className="agent-definition-dialog subagent-library-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={t('settings.subagentLibrary.action')}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="agent-definition-dialog-heading">
          <div className="agent-definition-dialog-icon subagent-library-icon">
            <PersonIcon />
          </div>
          <div>
            <span>{t('settings.subagentsEyebrow')}</span>
            <h2>{t('settings.subagentLibrary.action')}</h2>
            <p>{t('settings.subagentLibrary.description')}</p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            className="agent-definition-dialog-close"
            aria-label={t('common.close')}
            disabled={busyId !== null}
            onClick={onClose}
          >
            <Cross2Icon />
          </button>
        </header>

        <div className="agent-definition-dialog-body subagent-library-body">
          {loading ? (
            <div className="subagent-library-state">
              <ReloadIcon className="managed-resource-spin" />
              <span>{t('settings.subagentLibrary.loading')}</span>
            </div>
          ) : null}
          {!loading && templates.length === 0 ? (
            <div className="subagent-library-state">
              <PersonIcon />
              <span>{t('settings.subagentLibrary.empty')}</span>
            </div>
          ) : null}
          {!loading
            ? templates.map((template) => (
                <article key={template.id}>
                  <div className="subagent-library-template-icon">
                    <PersonIcon />
                  </div>
                  <div>
                    <span>{template.category}</span>
                    <strong>{template.display_name || template.name}</strong>
                    <p>{template.description || t('settings.noDescription')}</p>
                    <small>
                      {template.model} · v{template.version} ·{' '}
                      {t('settings.subagentLibrary.installCount', {
                        count: template.install_count,
                      })}
                    </small>
                    <div>
                      {template.tags.map((tag) => (
                        <em key={tag}>{tag}</em>
                      ))}
                    </div>
                  </div>
                  <button
                    type="button"
                    disabled={busyId !== null}
                    onClick={() => onInstall(template)}
                  >
                    {busyId === template.id ? (
                      <ReloadIcon className="managed-resource-spin" />
                    ) : (
                      <PlusIcon />
                    )}
                    {t('settings.subagentLibrary.install')}
                  </button>
                </article>
              ))
            : null}
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
            <button type="button" disabled={busyId !== null} onClick={onClose}>
              {t('common.close')}
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}
