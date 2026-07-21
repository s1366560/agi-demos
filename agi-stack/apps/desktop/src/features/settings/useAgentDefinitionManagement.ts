import { useCallback, useEffect, useRef, useState } from 'react';

import { DesktopApiClient } from '../../api/client';
import type {
  DesktopRuntimeConfig,
  ManagedAgentDefinition,
  ManagedAgentDefinitionMutation,
} from '../../types';

export function useAgentDefinitionManagement({
  active,
  config,
  contextKey,
  canManage,
  onReload,
  onSaved,
  onDeleted,
}: {
  active: boolean;
  config: DesktopRuntimeConfig;
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
  const contextKeyRef = useRef(contextKey);
  contextKeyRef.current = contextKey;

  useEffect(() => {
    setDefinition(undefined);
    setBusy(false);
    setError(null);
  }, [active, contextKey]);

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
        const client = new DesktopApiClient(config);
        const saved = definition
          ? await client.updateManagedAgentDefinition(definition.id, input)
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
    [canManage, config, contextKey, definition, onReload, onSaved]
  );

  const remove = useCallback(async () => {
    if (!definition || !canManage) return;
    const requestContextKey = contextKey;
    setBusy(true);
    setError(null);
    try {
      await new DesktopApiClient(config).deleteManagedAgentDefinition(definition.id);
      if (contextKeyRef.current !== requestContextKey) return;
      setDefinition(undefined);
      onDeleted();
      await onReload();
    } catch (caught) {
      if (contextKeyRef.current === requestContextKey) setError(errorMessage(caught));
    } finally {
      if (contextKeyRef.current === requestContextKey) setBusy(false);
    }
  }, [canManage, config, contextKey, definition, onDeleted, onReload]);

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
