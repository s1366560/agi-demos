import {
  ComponentInstanceIcon,
  Cross2Icon,
  ExclamationTriangleIcon,
  ReloadIcon,
  TrashIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { ManagedPlugin } from '../../types';
import { useModalDialog } from './useModalDialog';

import './PluginManagementDialogs.css';

export function PluginUninstallDialog({
  plugin,
  busy,
  error,
  onClose,
  onUninstall,
}: {
  plugin: ManagedPlugin;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onUninstall: () => void;
}) {
  const { t } = useI18n();
  const dialogRef = useModalDialog({ active: true, nested: true, onClose });

  return (
    <DialogFrame
      dialogRef={dialogRef}
      title={t('settings.pluginManager.uninstall')}
      description={t('settings.pluginManager.uninstallDescription')}
      busy={busy}
      onClose={onClose}
    >
      <div className="plugin-management-body compact">
        <div className="plugin-management-state">
          <ComponentInstanceIcon />
          <span>
            <strong>{plugin.plugin_id}</strong>
            <code>{plugin.version}</code>
          </span>
        </div>
        <p>{t('settings.pluginManager.uninstallConfirmation')}</p>
        <DialogError error={error} />
      </div>
      <footer className="plugin-management-footer">
        <button type="button" className="secondary" disabled={busy} onClick={onClose}>
          {t('common.cancel')}
        </button>
        <button type="button" className="danger" disabled={busy} onClick={onUninstall}>
          {busy ? <ReloadIcon className="managed-resource-spin" /> : <TrashIcon />}
          {t('settings.pluginManager.confirmUninstall')}
        </button>
      </footer>
    </DialogFrame>
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
    <div
      className="plugin-management-backdrop"
      role="presentation"
      onMouseDown={() => !busy && onClose()}
    >
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
