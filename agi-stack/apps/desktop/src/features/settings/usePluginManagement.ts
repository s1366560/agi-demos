import { useCallback, useEffect, useRef, useState } from 'react';

import { DesktopApiClient } from '../../api/client';
import type {
  DesktopRuntimeConfig,
  ManagedPlugin,
  PluginConfigRecord,
  PluginConfigSchema,
  UpdatePluginConfigRequest,
} from '../../types';

export type PluginDialogState =
  | { kind: 'install'; key: string }
  | {
      kind: 'config';
      key: string;
      plugin: ManagedPlugin;
      schema: PluginConfigSchema | null;
      record: PluginConfigRecord | null;
      loading: boolean;
      confirmUninstall: boolean;
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
  const [reloadBusy, setReloadBusy] = useState(false);
  const [reloadError, setReloadError] = useState<string | null>(null);
  const contextKeyRef = useRef(contextKey);
  contextKeyRef.current = contextKey;

  useEffect(() => {
    setDialog(null);
    setDialogBusy(false);
    setDialogError(null);
    setReloadBusy(false);
    setReloadError(null);
  }, [active, contextKey]);

  const closeDialog = useCallback(() => {
    if (!dialogBusy) setDialog(null);
  }, [dialogBusy]);

  const openInstall = useCallback(() => {
    if (!canManage) return;
    setDialogError(null);
    setDialog({ kind: 'install', key: `install:${crypto.randomUUID()}` });
  }, [canManage]);

  const openConfig = useCallback(
    async (plugin: ManagedPlugin, confirmUninstall = false) => {
      if (!canManage) return;
      const requestContextKey = contextKey;
      const key = `${plugin.id}:${confirmUninstall ? 'uninstall' : 'config'}:${crypto.randomUUID()}`;
      setDialogError(null);
      setDialog({
        kind: 'config',
        key,
        plugin,
        schema: null,
        record: null,
        loading: !confirmUninstall,
        confirmUninstall,
      });
      if (confirmUninstall) return;
      try {
        const client = new DesktopApiClient(config);
        const [schema, record] = await Promise.all([
          client.getManagedPluginConfigSchema(plugin.name),
          client.getManagedPluginConfig(plugin.name),
        ]);
        if (contextKeyRef.current !== requestContextKey) return;
        setDialog((current) =>
          current?.kind === 'config' && current.key === key
            ? { ...current, key: `${key}:ready`, schema, record, loading: false }
            : current,
        );
      } catch (caught) {
        if (contextKeyRef.current !== requestContextKey) return;
        setDialog((current) =>
          current?.kind === 'config' && current.key === key
            ? { ...current, loading: false }
            : current,
        );
        setDialogError(errorMessage(caught));
      }
    },
    [canManage, config, contextKey],
  );

  const install = useCallback(
    async (requirement: string) => {
      if (!canManage || dialog?.kind !== 'install') return;
      const requestContextKey = contextKey;
      setDialogBusy(true);
      setDialogError(null);
      try {
        await new DesktopApiClient(config).installManagedPlugin(requirement);
        if (contextKeyRef.current !== requestContextKey) return;
        setDialog(null);
        await onReload();
      } catch (caught) {
        if (contextKeyRef.current === requestContextKey) setDialogError(errorMessage(caught));
      } finally {
        if (contextKeyRef.current === requestContextKey) setDialogBusy(false);
      }
    },
    [canManage, config, contextKey, dialog, onReload],
  );

  const reload = useCallback(async () => {
    if (!canManage) return;
    const requestContextKey = contextKey;
    setReloadBusy(true);
    setReloadError(null);
    try {
      await new DesktopApiClient(config).reloadManagedPlugins();
      if (contextKeyRef.current === requestContextKey) await onReload();
    } catch (caught) {
      if (contextKeyRef.current === requestContextKey) setReloadError(errorMessage(caught));
    } finally {
      if (contextKeyRef.current === requestContextKey) setReloadBusy(false);
    }
  }, [canManage, config, contextKey, onReload]);

  const saveConfig = useCallback(
    async (input: UpdatePluginConfigRequest) => {
      if (!canManage || dialog?.kind !== 'config') return;
      const requestContextKey = contextKey;
      setDialogBusy(true);
      setDialogError(null);
      try {
        await new DesktopApiClient(config).updateManagedPluginConfig(dialog.plugin.name, input);
        if (contextKeyRef.current !== requestContextKey) return;
        setDialog(null);
        await onReload();
      } catch (caught) {
        if (contextKeyRef.current === requestContextKey) setDialogError(errorMessage(caught));
      } finally {
        if (contextKeyRef.current === requestContextKey) setDialogBusy(false);
      }
    },
    [canManage, config, contextKey, dialog, onReload],
  );

  const uninstall = useCallback(async () => {
    if (!canManage || dialog?.kind !== 'config') return;
    const requestContextKey = contextKey;
    setDialogBusy(true);
    setDialogError(null);
    try {
      await new DesktopApiClient(config).uninstallManagedPlugin(dialog.plugin.name);
      if (contextKeyRef.current !== requestContextKey) return;
      setDialog(null);
      onUninstalled();
      await onReload();
    } catch (caught) {
      if (contextKeyRef.current === requestContextKey) setDialogError(errorMessage(caught));
    } finally {
      if (contextKeyRef.current === requestContextKey) setDialogBusy(false);
    }
  }, [canManage, config, contextKey, dialog, onReload, onUninstalled]);

  return {
    dialog,
    dialogBusy,
    dialogError,
    reloadBusy,
    reloadError,
    closeDialog,
    openInstall,
    openConfig,
    install,
    reload,
    saveConfig,
    uninstall,
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
