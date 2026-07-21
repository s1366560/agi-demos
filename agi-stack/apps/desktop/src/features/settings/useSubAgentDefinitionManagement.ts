import { useCallback, useEffect, useRef, useState } from 'react';

import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig, ManagedSubAgent, ManagedSubAgentMutation } from '../../types';

export function useSubAgentDefinitionManagement({
  active,
  config,
  contextKey,
  canManage,
  onReload,
  onDeleted,
}: {
  active: boolean;
  config: DesktopRuntimeConfig;
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
        const client = new DesktopApiClient(config);
        const saved = definition
          ? await client.updateManagedSubAgent(definition.id, input)
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
    [canManage, config, contextKey, definition, onReload],
  );

  const remove = useCallback(async () => {
    if (!definition || definition.source === 'filesystem' || !canManage) return;
    const requestContextKey = contextKey;
    setBusy(true);
    setError(null);
    try {
      await new DesktopApiClient(config).deleteManagedSubAgent(definition.id);
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
