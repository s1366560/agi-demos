import { useCallback, useEffect, useRef, useState } from 'react';

import type { DesktopTenantSubAgentDefinitionsClientV2 } from '../../plugins/desktopTenantSubAgentDefinitionsAuthorityModuleV2';
import type { ManagedSubAgent, ManagedSubAgentMutation } from '../../types';

export function useSubAgentDefinitionManagement({
  active,
  client,
  contextKey,
  canManage,
  onReload,
  onDeleted,
}: {
  active: boolean;
  client: DesktopTenantSubAgentDefinitionsClientV2;
  contextKey: string;
  canManage: boolean;
  onReload: (preferredSelectionId?: string) => Promise<void>;
  onDeleted: () => void;
}) {
  const [definition, setDefinition] = useState<ManagedSubAgent | null | undefined>(undefined);
  const [dialogKey, setDialogKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const contextKeyRef = useRef(contextKey);
  contextKeyRef.current = contextKey;

  useEffect(() => {
    setDefinition(undefined);
    setBusy(false);
    setError(null);
  }, [active, contextKey]);

  const open = useCallback(
    (next: ManagedSubAgent | null) => {
      if (!canManage || next?.source === 'filesystem') return;
      setError(null);
      setDefinition(next);
      setDialogKey(`${next?.id ?? 'new'}:${crypto.randomUUID()}`);
    },
    [canManage],
  );

  const close = useCallback(() => {
    if (!busy) setDefinition(undefined);
  }, [busy]);

  const save = useCallback(
    async (input: ManagedSubAgentMutation) => {
      if (definition === undefined || !canManage) return;
      const requestContextKey = contextKey;
      setBusy(true);
      setError(null);
      try {
        const saved = definition
          ? await client.updateManagedSubAgent(
              definition.id,
              input,
              definition.revision,
            )
          : await client.createManagedSubAgent(input);
        if (contextKeyRef.current !== requestContextKey) return;
        setDefinition(undefined);
        await onReload(saved.id);
      } catch (caught) {
        if (contextKeyRef.current === requestContextKey) setError(errorMessage(caught));
      } finally {
        if (contextKeyRef.current === requestContextKey) setBusy(false);
      }
    },
    [canManage, client, contextKey, definition, onReload],
  );

  const remove = useCallback(async () => {
    if (!definition || definition.source === 'filesystem' || !canManage) return;
    const requestContextKey = contextKey;
    setBusy(true);
    setError(null);
    try {
      await client.deleteManagedSubAgent(
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
    open,
    close,
    save,
    remove,
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
