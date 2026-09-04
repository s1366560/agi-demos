import { useCallback, useEffect, useRef, useState } from 'react';

import { ManagedResourcesClient } from '../../api/managedResourcesClient';
import type { DesktopTenantTemplatesOperationsV2 } from '../../plugins/desktopTenantTemplatesAuthorityModuleV2';
import type {
  DesktopRuntimeConfig,
  ManagedSubAgent,
  ManagedSubAgentTemplate,
} from '../../types';

export type SubAgentLibraryDialogState = {
  key: string;
  templates: ManagedSubAgentTemplate[];
  loading: boolean;
};

export function useSubAgentLibraryManagement({
  active,
  config,
  contextKey,
  canManage,
  tenantTemplatesOperationsV2,
  onReload,
}: {
  active: boolean;
  config: DesktopRuntimeConfig;
  contextKey: string;
  canManage: boolean;
  tenantTemplatesOperationsV2: DesktopTenantTemplatesOperationsV2;
  onReload: (preferredSelectionId?: string) => Promise<void>;
}) {
  const [dialog, setDialog] = useState<SubAgentLibraryDialogState | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [importBusyId, setImportBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const contextKeyRef = useRef(contextKey);
  contextKeyRef.current = contextKey;

  useEffect(() => {
    setDialog(null);
    setBusyId(null);
    setImportBusyId(null);
    setError(null);
  }, [active, contextKey]);

  const open = useCallback(async () => {
    if (!canManage) return;
    const requestContextKey = contextKey;
    setError(null);
    setDialog({ key: crypto.randomUUID(), templates: [], loading: true });
    try {
      const result = await tenantTemplatesOperationsV2.loadTenantTemplates({
        config,
        scope: Object.freeze({ authority: config.mode, tenantId: config.tenantId }),
        query: Object.freeze({ page: 1, pageSize: 100 }),
      });
      if (contextKeyRef.current !== requestContextKey) return;
      setDialog((current) =>
        current ? { ...current, templates: [...result.templates], loading: false } : null,
      );
    } catch (caught) {
      if (contextKeyRef.current !== requestContextKey) return;
      setDialog((current) => (current ? { ...current, loading: false } : null));
      setError(errorMessage(caught));
    }
  }, [canManage, config, contextKey, tenantTemplatesOperationsV2]);

  const close = useCallback(() => {
    if (!busyId) setDialog(null);
  }, [busyId]);

  const install = useCallback(
    async (template: ManagedSubAgentTemplate) => {
      if (!canManage || busyId) return;
      const requestContextKey = contextKey;
      setBusyId(template.id);
      setError(null);
      try {
        const created = await tenantTemplatesOperationsV2.installTenantTemplate({
          config,
          scope: Object.freeze({ authority: config.mode, tenantId: config.tenantId }),
          templateId: template.id,
        });
        if (contextKeyRef.current !== requestContextKey) return;
        setDialog(null);
        await onReload(created.id);
      } catch (caught) {
        if (contextKeyRef.current === requestContextKey) setError(errorMessage(caught));
      } finally {
        if (contextKeyRef.current === requestContextKey) setBusyId(null);
      }
    },
    [busyId, canManage, config, contextKey, onReload, tenantTemplatesOperationsV2],
  );

  const importFilesystem = useCallback(
    async (subagent: ManagedSubAgent) => {
      if (!canManage || importBusyId || subagent.source !== 'filesystem') return;
      const requestContextKey = contextKey;
      setImportBusyId(subagent.id);
      setError(null);
      try {
        const created = await new ManagedResourcesClient(config).importManagedFilesystemSubAgent(
          subagent.name,
          config.projectId || undefined,
        );
        if (contextKeyRef.current !== requestContextKey) return;
        await onReload(created.id);
      } catch (caught) {
        if (contextKeyRef.current === requestContextKey) setError(errorMessage(caught));
      } finally {
        if (contextKeyRef.current === requestContextKey) setImportBusyId(null);
      }
    },
    [canManage, config, contextKey, importBusyId, onReload],
  );

  return { dialog, busyId, importBusyId, error, open, close, install, importFilesystem };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
