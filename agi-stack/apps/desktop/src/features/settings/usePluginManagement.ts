import { useCallback, useEffect, useRef, useState } from 'react';

import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig, ManagedPlugin } from '../../types';

export type PluginDialogState = {
  kind: 'uninstall';
  key: string;
  plugin: ManagedPlugin;
};

export function usePluginManagement({
  active,
  config,
  contextKey,
  canManage,
  onReload,
  onUninstalled,
}: {
  active: boolean;
  config: DesktopRuntimeConfig;
  contextKey: string;
  canManage: boolean;
  onReload: () => Promise<void>;
  onUninstalled: () => void;
}) {
  const [dialog, setDialog] = useState<PluginDialogState | null>(null);
  const [dialogBusy, setDialogBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const contextKeyRef = useRef(contextKey);
  contextKeyRef.current = contextKey;

  useEffect(() => {
    setDialog(null);
    setDialogBusy(false);
    setDialogError(null);
  }, [active, contextKey]);

  const closeDialog = useCallback(() => {
    if (!dialogBusy) setDialog(null);
  }, [dialogBusy]);

  const openUninstall = useCallback(
    (plugin: ManagedPlugin) => {
      if (!canManage || plugin.install_status !== 'installed' || plugin.revoked) return;
      setDialogError(null);
      setDialog({
        kind: 'uninstall',
        key: `${plugin.id}:uninstall:${crypto.randomUUID()}`,
        plugin,
      });
    },
    [canManage],
  );

  const uninstall = useCallback(async () => {
    if (!canManage || dialog?.kind !== 'uninstall') return;
    const requestContextKey = contextKey;
    setDialogBusy(true);
    setDialogError(null);
    try {
      await new DesktopApiClient(config).uninstallMarketplacePlugin(
        dialog.plugin.plugin_id,
        dialog.plugin.version,
      );
      if (contextKeyRef.current !== requestContextKey) return;
      setDialog(null);
      onUninstalled();
      await onReload();
    } catch (caught) {
      if (contextKeyRef.current === requestContextKey) {
        setDialogError(errorMessage(caught));
      }
    } finally {
      if (contextKeyRef.current === requestContextKey) setDialogBusy(false);
    }
  }, [canManage, config, contextKey, dialog, onReload, onUninstalled]);

  return {
    dialog,
    dialogBusy,
    dialogError,
    closeDialog,
    openUninstall,
    uninstall,
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
