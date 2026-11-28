import { useCallback, useEffect, useRef, useState } from 'react';

import {
  buildMarketplaceInstallRequest,
  marketplaceInstallAvailability,
} from '../../api/pluginMarketplaceModel';
import type { DesktopPluginMarketplaceManagementOperationsV2 } from '../../plugins/desktopPluginMarketplaceAuthorityModulesV2';
import type { DesktopRuntimeConfig, ManagedPlugin } from '../../types';

export type PluginDialogState = {
  kind: 'uninstall' | 'install';
  key: string;
  plugin: ManagedPlugin;
};

export function usePluginManagement({
  active,
  config,
  pluginMarketplaceOperationsV2,
  contextKey,
  canManage,
  onReload,
  onUninstalled,
}: {
  active: boolean;
  config: DesktopRuntimeConfig;
  pluginMarketplaceOperationsV2: DesktopPluginMarketplaceManagementOperationsV2;
  contextKey: string;
  canManage: boolean;
  onReload: () => Promise<void>;
  onUninstalled: () => void;
}) {
  const [dialog, setDialog] = useState<PluginDialogState | null>(null);
  const [dialogBusy, setDialogBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const contextKeyRef = useRef(contextKey);
  const mutationAbortRef = useRef<AbortController | null>(null);
  contextKeyRef.current = contextKey;

  useEffect(() => {
    mutationAbortRef.current?.abort();
    mutationAbortRef.current = null;
    setDialog(null);
    setDialogBusy(false);
    setDialogError(null);
    return () => mutationAbortRef.current?.abort();
  }, [active, contextKey]);

  const closeDialog = useCallback(() => {
    if (!dialogBusy) setDialog(null);
  }, [dialogBusy]);

  const openUninstall = useCallback(
    (plugin: ManagedPlugin) => {
      if (!canManage || plugin.install_status !== 'installed') return;
      setDialogError(null);
      setDialog({
        kind: 'uninstall',
        key: `${plugin.id}:uninstall:${crypto.randomUUID()}`,
        plugin,
      });
    },
    [canManage],
  );

  const openInstall = useCallback(
    (plugin: ManagedPlugin) => {
      if (!canManage) return;
      if (marketplaceInstallAvailability(config.mode, plugin) !== 'ready') return;
      setDialogError(null);
      setDialog({
        kind: 'install',
        key: `${plugin.id}:install:${crypto.randomUUID()}`,
        plugin,
      });
    },
    [canManage, config.mode],
  );

  const uninstall = useCallback(async () => {
    if (!canManage || dialog?.kind !== 'uninstall') return;
    const requestContextKey = contextKey;
    const controller = new AbortController();
    mutationAbortRef.current?.abort();
    mutationAbortRef.current = controller;
    setDialogBusy(true);
    setDialogError(null);
    try {
      await pluginMarketplaceOperationsV2.uninstallMarketplacePlugin(
        config,
        dialog.plugin.plugin_id,
        dialog.plugin.version,
        controller.signal,
      );
      if (contextKeyRef.current !== requestContextKey) return;
      setDialog(null);
      onUninstalled();
      await onReload();
    } catch (caught) {
      if (contextKeyRef.current === requestContextKey && !controller.signal.aborted) {
        setDialogError(errorMessage(caught));
      }
    } finally {
      if (mutationAbortRef.current === controller) mutationAbortRef.current = null;
      if (contextKeyRef.current === requestContextKey && !controller.signal.aborted) {
        setDialogBusy(false);
      }
    }
  }, [
    canManage,
    config,
    contextKey,
    dialog,
    onReload,
    onUninstalled,
    pluginMarketplaceOperationsV2,
  ]);

  const install = useCallback(async () => {
    if (!canManage || dialog?.kind !== 'install') return;
    const request = buildMarketplaceInstallRequest(dialog.plugin, config.tenantId);
    if (!request) {
      setDialogError('marketplace_install_unsigned');
      return;
    }
    const requestContextKey = contextKey;
    const controller = new AbortController();
    mutationAbortRef.current?.abort();
    mutationAbortRef.current = controller;
    setDialogBusy(true);
    setDialogError(null);
    try {
      const outcome = await pluginMarketplaceOperationsV2.installMarketplacePlugin(
        config,
        request,
        controller.signal,
      );
      if (contextKeyRef.current !== requestContextKey) return;
      if (outcome.status !== 'approved') {
        setDialogError(outcome.reason || `marketplace_install_${outcome.status}`);
        return;
      }
      setDialog(null);
      await onReload();
    } catch (caught) {
      if (contextKeyRef.current === requestContextKey && !controller.signal.aborted) {
        setDialogError(errorMessage(caught));
      }
    } finally {
      if (mutationAbortRef.current === controller) mutationAbortRef.current = null;
      if (contextKeyRef.current === requestContextKey && !controller.signal.aborted) {
        setDialogBusy(false);
      }
    }
  }, [canManage, config, contextKey, dialog, onReload, pluginMarketplaceOperationsV2]);

  return {
    dialog,
    dialogBusy,
    dialogError,
    closeDialog,
    openUninstall,
    uninstall,
    openInstall,
    install,
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
