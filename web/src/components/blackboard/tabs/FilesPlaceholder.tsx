import { useTranslation } from 'react-i18next';

export function FilesPlaceholder() {
  const { t } = useTranslation();

  return (
    <div className="rounded-xl border border-dashed border-border-separator bg-surface-light p-8 text-center dark:border-border-dark dark:bg-surface-dark">
      <div className="text-lg font-semibold text-text-primary dark:text-text-inverse">
        {t('blackboard.filesUnavailableTitle', 'Shared files are not wired here yet')}
      </div>
      <p className="mx-auto mt-3 max-w-2xl text-sm leading-7 text-text-secondary dark:text-text-muted">
        {t(
          'blackboard.filesUnavailableBody',
          'The central blackboard already combines discussion, goals, and execution. File operations can be added later when a workspace-scoped file endpoint is available.'
        )}
      </p>
    </div>
  );
}
