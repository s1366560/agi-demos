import { useCallback, useEffect, useRef, useState } from 'react';

import { DesktopApiClient } from '../../api/client';
import type {
  DesktopRuntimeConfig,
  ManagedPlugin,
  PluginActionDetails,
  PluginActionResponse,
  PluginConfigRecord,
  PluginConfigSchema,
  PluginDiagnostic,
  UpdatePluginConfigRequest,
} from '../../types';
import {
  prependPluginActionTimeline,
  type PluginActionTimelineEntry,
} from './pluginManagementModel';

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
  const [activityOpen, setActivityOpen] = useState(false);
  const [activityLoading, setActivityLoading] = useState(false);
  const [activityError, setActivityError] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState<PluginDiagnostic[]>([]);
  const [lastActionDetails, setLastActionDetails] = useState<PluginActionDetails | null>(null);
  const [actionTimeline, setActionTimeline] = useState<PluginActionTimelineEntry[]>([]);
  const contextKeyRef = useRef(contextKey);
  contextKeyRef.current = contextKey;

  useEffect(() => {
    setDialog(null);
    setDialogBusy(false);
    setDialogError(null);
    setReloadBusy(false);
    setReloadError(null);
    setActivityOpen(false);
    setActivityLoading(false);
    setActivityError(null);
    setDiagnostics([]);
    setLastActionDetails(null);
    setActionTimeline([]);
  }, [active, contextKey]);

  const recordAction = useCallback(
    (response: PluginActionResponse, fallbackAction: string) => {
      const details = response.details ?? null;
      setLastActionDetails(details);
      if (details?.diagnostics) setDiagnostics(details.diagnostics);
      setActionTimeline((current) =>
        prependPluginActionTimeline(current, response, fallbackAction),
      );
    },
    [],
  );

  const refreshActivity = useCallback(async () => {
    const requestContextKey = contextKey;
    setActivityLoading(true);
    setActivityError(null);
    try {
      const runtime = await new DesktopApiClient(config).getManagedPluginRuntime();
      if (contextKeyRef.current === requestContextKey) setDiagnostics(runtime.diagnostics);
    } catch (caught) {
      if (contextKeyRef.current === requestContextKey) setActivityError(errorMessage(caught));
    } finally {
      if (contextKeyRef.current === requestContextKey) setActivityLoading(false);
    }
  }, [config, contextKey]);

  const openActivity = useCallback(() => {
    if (!canManage) return;
    setActivityOpen(true);
    void refreshActivity();
  }, [canManage, refreshActivity]);

  const closeActivity = useCallback(() => {
    setActivityOpen(false);
  }, []);

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
        const response = await new DesktopApiClient(config).installManagedPlugin(requirement);
        if (contextKeyRef.current !== requestContextKey) return;
        recordAction(response, 'install');
        setDialog(null);
        await onReload();
      } catch (caught) {
        if (contextKeyRef.current === requestContextKey) setDialogError(errorMessage(caught));
      } finally {
        if (contextKeyRef.current === requestContextKey) setDialogBusy(false);
      }
    },
    [canManage, config, contextKey, dialog, onReload, recordAction],
  );

  const reload = useCallback(async () => {
    if (!canManage) return;
    const requestContextKey = contextKey;
    setReloadBusy(true);
    setReloadError(null);
    try {
      const response = await new DesktopApiClient(config).reloadManagedPlugins();
      if (contextKeyRef.current === requestContextKey) {
        recordAction(response, 'reload');
        await onReload();
      }
    } catch (caught) {
      if (contextKeyRef.current === requestContextKey) setReloadError(errorMessage(caught));
    } finally {
      if (contextKeyRef.current === requestContextKey) setReloadBusy(false);
    }
  }, [canManage, config, contextKey, onReload, recordAction]);

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
      const response = await new DesktopApiClient(config).uninstallManagedPlugin(
        dialog.plugin.name,
      );
      if (contextKeyRef.current !== requestContextKey) return;
      recordAction(response, 'uninstall');
      setDialog(null);
      onUninstalled();
      await onReload();
    } catch (caught) {
      if (contextKeyRef.current === requestContextKey) setDialogError(errorMessage(caught));
    } finally {
      if (contextKeyRef.current === requestContextKey) setDialogBusy(false);
    }
  }, [canManage, config, contextKey, dialog, onReload, onUninstalled, recordAction]);

  return {
    dialog,
    dialogBusy,
    dialogError,
    reloadBusy,
    reloadError,
    activityOpen,
    activityLoading,
    activityError,
    diagnostics,
    lastActionDetails,
    actionTimeline,
    closeDialog,
    openInstall,
    openConfig,
    install,
    reload,
    openActivity,
    closeActivity,
    refreshActivity,
    recordAction,
    saveConfig,
    uninstall,
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
