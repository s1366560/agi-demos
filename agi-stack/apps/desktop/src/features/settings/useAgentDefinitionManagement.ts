import { useCallback, useEffect, useRef, useState } from 'react';

import type { DesktopTenantAgentDefinitionsClientV2 } from '../../plugins/desktopTenantAgentDefinitionsAuthorityModuleV2';
import type {
  ManagedAgentDefinition,
  ManagedAgentDefinitionMutation,
  ManagedExternalAcpAgent,
} from '../../types';

export function useAgentDefinitionManagement({
  active,
  client,
  contextKey,
  canManage,
  onReload,
  onSaved,
  onDeleted,
}: {
  active: boolean;
  client: DesktopTenantAgentDefinitionsClientV2;
  contextKey: string;
  canManage: boolean;
  onReload: () => Promise<void>;
  onSaved: (definitionId: string) => void;
  onDeleted: () => void;
}) {
  const [definition, setDefinition] = useState<ManagedAgentDefinition | null | undefined>();
  const [dialogKey, setDialogKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [externalAcpAgents, setExternalAcpAgents] = useState<ManagedExternalAcpAgent[]>([]);
  const [externalAcpAgentsLoading, setExternalAcpAgentsLoading] = useState(false);
  const [externalAcpAgentsError, setExternalAcpAgentsError] = useState<string | null>(null);
  const contextKeyRef = useRef(contextKey);
  contextKeyRef.current = contextKey;

  useEffect(() => {
    setDefinition(undefined);
    setBusy(false);
    setError(null);
    setExternalAcpAgents([]);
    setExternalAcpAgentsLoading(false);
    setExternalAcpAgentsError(null);
  }, [active, contextKey]);

  useEffect(() => {
    if (definition === undefined) return;
    const requestContextKey = contextKey;
    const controller = new AbortController();
    setExternalAcpAgentsLoading(true);
    setExternalAcpAgentsError(null);
    void client
      .listManagedExternalAcpAgents(controller.signal)
      .then((agents) => {
        if (contextKeyRef.current === requestContextKey) setExternalAcpAgents(agents);
      })
      .catch((caught) => {
        if (!controller.signal.aborted && contextKeyRef.current === requestContextKey) {
          setExternalAcpAgents([]);
          setExternalAcpAgentsError(errorMessage(caught));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted && contextKeyRef.current === requestContextKey) {
          setExternalAcpAgentsLoading(false);
        }
      });
    return () => controller.abort();
  }, [client, contextKey, definition]);

  const open = useCallback(
    (next: ManagedAgentDefinition | null) => {
      if (!canManage) return;
      setError(null);
      setDefinition(next);
      setDialogKey(`${next?.id ?? 'new'}:${crypto.randomUUID()}`);
    },
    [canManage]
  );

  const close = useCallback(() => {
    if (!busy) setDefinition(undefined);
  }, [busy]);

  const save = useCallback(
    async (input: ManagedAgentDefinitionMutation) => {
      if (definition === undefined || !canManage) return;
      const requestContextKey = contextKey;
      setBusy(true);
      setError(null);
      try {
        const saved = definition
          ? await client.updateManagedAgentDefinition(
              definition.id,
              input,
              definition.revision,
            )
          : await client.createManagedAgentDefinition(input);
        if (contextKeyRef.current !== requestContextKey) return;
        setDefinition(undefined);
        await onReload();
        onSaved(saved.id);
      } catch (caught) {
        if (contextKeyRef.current === requestContextKey) setError(errorMessage(caught));
      } finally {
        if (contextKeyRef.current === requestContextKey) setBusy(false);
      }
    },
    [canManage, client, contextKey, definition, onReload, onSaved]
  );

  const remove = useCallback(async () => {
    if (!definition || !canManage) return;
    const requestContextKey = contextKey;
    setBusy(true);
    setError(null);
    try {
      await client.deleteManagedAgentDefinition(
        definition.id,
        definition.revision,
      );
      if (contextKeyRef.current !== requestContextKey) return;
      setDefinition(undefined);
      onDeleted();
      await onReload();
    } catch (caught) {
      if (contextKeyRef.current === requestContextKey) setError(errorMessage(caught));
    } finally {
      if (contextKeyRef.current === requestContextKey) setBusy(false);
    }
  }, [canManage, client, contextKey, definition, onDeleted, onReload]);

  return {
    dialog: definition === undefined ? null : { key: dialogKey, definition },
    busy,
    error,
    externalAcpAgents,
    externalAcpAgentsLoading,
    externalAcpAgentsError,
    open,
    close,
    save,
    remove,
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
