import { useState } from 'react';

import {
  ComponentInstanceIcon,
  Cross2Icon,
  DownloadIcon,
  ExclamationTriangleIcon,
  ReloadIcon,
  TrashIcon,
} from '@radix-ui/react-icons';

import { marketplacePluginPermissions } from '../../api/pluginMarketplaceModel';
import { useI18n } from '../../i18n';
import type { ManagedPlugin } from '../../types';
import { useModalDialog } from './useModalDialog';

import './PluginManagementDialogs.css';

export function PluginInstallDialog({
  plugin,
  busy,
  error,
  onClose,
  onInstall,
}: {
  plugin: ManagedPlugin;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onInstall: () => void;
}) {
  const { t } = useI18n();
  const dialogRef = useModalDialog({ active: true, nested: true, onClose });
  const [scopeApproved, setScopeApproved] = useState(false);
  const permissions = marketplacePluginPermissions(plugin.manifest);

  return (
    <DialogFrame
      dialogRef={dialogRef}
      title={t('settings.pluginManager.install')}
      description={t('settings.pluginManager.installDescription')}
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
        <p>{plugin.publisher}</p>
        <fieldset disabled={busy}>
          <legend>{t('settings.pluginManager.declaredPermissions')}</legend>
          {permissions.length === 0 ? (
            <p>{t('settings.pluginManager.noDeclaredPermissions')}</p>
          ) : (
            <ul>
              {permissions.map((permission) => (
                <li key={permission}>
                  <code>{permission}</code>
                </li>
              ))}
            </ul>
          )}
          <label>
            <input
              type="checkbox"
              checked={scopeApproved}
              onChange={(event) => setScopeApproved(event.target.checked)}
            />
            {t('settings.pluginManager.approveTenantPermissions')}
          </label>
        </fieldset>
        <DialogError error={error} />
      </div>
      <footer className="plugin-management-footer">
        <button type="button" className="secondary" disabled={busy} onClick={onClose}>
          {t('common.cancel')}
        </button>
        <button
          type="button"
          className="primary"
          disabled={busy || !scopeApproved}
          onClick={onInstall}
        >
          {busy ? <ReloadIcon className="managed-resource-spin" /> : <DownloadIcon />}
          {t('settings.pluginManager.confirmInstall')}
        </button>
      </footer>
    </DialogFrame>
  );
}

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
