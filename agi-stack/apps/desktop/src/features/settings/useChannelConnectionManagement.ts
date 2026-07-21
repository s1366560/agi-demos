import { useCallback, useEffect, useRef, useState } from 'react';

import { DesktopApiClient } from '../../api/client';
import type {
  CreateManagedChannelConfigRequest,
  DesktopRuntimeConfig,
  ManagedChannelConfig,
  ManagedChannelPluginCatalogItem,
  ManagedChannelPluginConfigSchema,
  UpdateManagedChannelConfigRequest,
} from '../../types';
import { legacyChannelConfigSchema } from './channelConnectionModel';

export type ChannelConnectionEditorState = {
  key: string;
  config: ManagedChannelConfig | null;
  channelType: string;
  schema: ManagedChannelPluginConfigSchema;
  loading: boolean;
};

export function useChannelConnectionManagement({
  active,
  config,
  contextKey,
  canManage,
}: {
  active: boolean;
  config: DesktopRuntimeConfig;
  contextKey: string;
  canManage: boolean;
}) {
  const [openState, setOpenState] = useState(false);
  const [configs, setConfigs] = useState<ManagedChannelConfig[]>([]);
  const [catalog, setCatalog] = useState<ManagedChannelPluginCatalogItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editor, setEditor] = useState<ChannelConnectionEditorState | null>(null);
  const contextKeyRef = useRef(contextKey);
  const requestIdRef = useRef(0);
  contextKeyRef.current = contextKey;

  useEffect(() => {
    requestIdRef.current += 1;
    setOpenState(false);
    setConfigs([]);
    setCatalog([]);
    setLoading(false);
    setBusyId(null);
    setError(null);
    setNotice(null);
    setEditor(null);
  }, [active, contextKey]);

  const reload = useCallback(async () => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    const requestContextKey = contextKey;
    setLoading(true);
    setError(null);
    try {
      const client = new DesktopApiClient(config);
      const [nextConfigs, nextCatalog] = await Promise.all([
        client.listManagedChannelConfigs(),
        client.listManagedChannelCatalog(),
      ]);
      if (requestId !== requestIdRef.current || contextKeyRef.current !== requestContextKey) return;
      setConfigs(nextConfigs);
      setCatalog(nextCatalog);
    } catch (caught) {
      if (requestId === requestIdRef.current && contextKeyRef.current === requestContextKey) {
        setError(errorMessage(caught));
      }
    } finally {
      if (requestId === requestIdRef.current && contextKeyRef.current === requestContextKey) {
        setLoading(false);
      }
    }
  }, [config, contextKey]);

  const open = useCallback(() => {
    if (!canManage || config.mode !== 'cloud' || !config.tenantId || !config.projectId) return;
    setOpenState(true);
    setNotice(null);
    void reload();
  }, [canManage, config.mode, config.projectId, config.tenantId, reload]);

  const close = useCallback(() => {
    if (busyId === null) {
      setOpenState(false);
      setEditor(null);
    }
  }, [busyId]);

  const loadEditor = useCallback(
    async (channelType: string, existing: ManagedChannelConfig | null) => {
      const requestContextKey = contextKey;
      const key = `${existing?.id ?? 'create'}:${channelType}:${crypto.randomUUID()}`;
      const catalogItem = catalog.find((item) => item.channel_type === channelType);
      const fallback = legacyChannelConfigSchema(channelType);
      setError(null);
      setEditor({ key, config: existing, channelType, schema: fallback, loading: true });
      try {
        const schema = catalogItem?.schema_supported
          ? await new DesktopApiClient(config).getManagedChannelSchema(channelType)
          : fallback;
        if (contextKeyRef.current !== requestContextKey) return;
        setEditor((current) =>
          current?.key === key ? { ...current, key: `${key}:ready`, schema, loading: false } : current,
        );
      } catch (caught) {
        if (contextKeyRef.current !== requestContextKey) return;
        setEditor((current) =>
          current?.key === key ? { ...current, schema: fallback, loading: false } : current,
        );
        setError(errorMessage(caught));
      }
    },
    [catalog, config, contextKey],
  );

  const openCreate = useCallback(() => {
    const first = catalog.find((item) => item.enabled && item.discovered) ?? catalog[0];
    if (first) void loadEditor(first.channel_type, null);
  }, [catalog, loadEditor]);

  const save = useCallback(
    async (body: CreateManagedChannelConfigRequest | UpdateManagedChannelConfigRequest) => {
      if (!editor || !canManage) return;
      const requestContextKey = contextKey;
      setBusyId(editor.config?.id ?? 'create');
      setError(null);
      try {
        const client = new DesktopApiClient(config);
        if (editor.config) {
          await client.updateManagedChannelConfig(
            editor.config.id,
            body as UpdateManagedChannelConfigRequest,
          );
        } else {
          await client.createManagedChannelConfig(body as CreateManagedChannelConfigRequest);
        }
        if (contextKeyRef.current !== requestContextKey) return;
        setNotice(editor.config ? 'updated' : 'created');
        setEditor(null);
        await reload();
      } catch (caught) {
        if (contextKeyRef.current === requestContextKey) setError(errorMessage(caught));
      } finally {
        if (contextKeyRef.current === requestContextKey) setBusyId(null);
      }
    },
    [canManage, config, contextKey, editor, reload],
  );

  const mutate = useCallback(
    async (target: ManagedChannelConfig, action: 'toggle' | 'test' | 'delete') => {
      if (!canManage) return;
      const requestContextKey = contextKey;
      setBusyId(target.id);
      setError(null);
      setNotice(null);
      try {
        const client = new DesktopApiClient(config);
        if (action === 'toggle') {
          await client.updateManagedChannelConfig(target.id, { enabled: !target.enabled });
        } else if (action === 'test') {
          const result = await client.testManagedChannelConfig(target.id);
          if (contextKeyRef.current !== requestContextKey) return;
          setNotice(result.success ? 'testSuccess' : `testFailure:${result.message}`);
        } else {
          await client.deleteManagedChannelConfig(target.id);
        }
        if (contextKeyRef.current !== requestContextKey) return;
        if (action === 'toggle') setNotice(target.enabled ? 'disabled' : 'enabled');
        if (action === 'delete') setNotice('deleted');
        await reload();
      } catch (caught) {
        if (contextKeyRef.current === requestContextKey) setError(errorMessage(caught));
      } finally {
        if (contextKeyRef.current === requestContextKey) setBusyId(null);
      }
    },
    [canManage, config, contextKey, reload],
  );

  return {
    open: openState,
    configs,
    catalog,
    loading,
    busyId,
    error,
    notice,
    editor,
    launch: open,
    close,
    reload,
    openCreate,
    openEdit: (target: ManagedChannelConfig) => void loadEditor(target.channel_type, target),
    changeType: (channelType: string) => void loadEditor(channelType, null),
    closeEditor: () => busyId === null && setEditor(null),
    save,
    toggle: (target: ManagedChannelConfig) => void mutate(target, 'toggle'),
    test: (target: ManagedChannelConfig) => void mutate(target, 'test'),
    remove: (target: ManagedChannelConfig) => void mutate(target, 'delete'),
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
