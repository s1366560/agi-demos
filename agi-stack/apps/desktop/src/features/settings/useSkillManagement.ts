import { useCallback, useEffect, useRef, useState } from 'react';

import { DesktopApiClient } from '../../api/client';
import type {
  DesktopRuntimeConfig,
  ManagedSkill,
  ManagedSkillCreateMutation,
  ManagedSkillMutation,
} from '../../types';

export type SkillDialogState = {
  key: string;
  skill: ManagedSkill | null;
  loading: boolean;
  contentReady: boolean;
};

export function useSkillManagement({
  active,
  config,
  contextKey,
  canCreate,
  onReload,
  onSaved,
  onDeleted,
}: {
  active: boolean;
  config: DesktopRuntimeConfig;
  contextKey: string;
  canCreate: boolean;
  onReload: () => Promise<void>;
  onSaved: (skillId: string) => void;
  onDeleted: () => void;
}) {
  const [dialog, setDialog] = useState<SkillDialogState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const contextKeyRef = useRef(contextKey);
  contextKeyRef.current = contextKey;

  useEffect(() => {
    setDialog(null);
    setBusy(false);
    setError(null);
  }, [active, contextKey]);

  const close = useCallback(() => {
    if (!busy) setDialog(null);
  }, [busy]);

  const open = useCallback(
    async (skill: ManagedSkill | null) => {
      if (!skill && !canCreate) return;
      const requestContextKey = contextKey;
      const key = `${skill?.id ?? 'new'}:${crypto.randomUUID()}`;
      setError(null);
      setDialog({ key, skill, loading: Boolean(skill), contentReady: !skill });
      if (!skill) return;
      try {
        const content = await new DesktopApiClient(config).getManagedSkillContent(skill.id);
        if (contextKeyRef.current !== requestContextKey) return;
        setDialog((current) =>
          current?.key === key
            ? {
                key: `${key}:ready`,
                skill: { ...skill, full_content: content.full_content },
                loading: false,
                contentReady: true,
              }
            : current
        );
      } catch (caught) {
        if (contextKeyRef.current !== requestContextKey) return;
        setDialog((current) => (current?.key === key ? { ...current, loading: false } : current));
        setError(errorMessage(caught));
      }
    },
    [canCreate, config, contextKey]
  );

  const save = useCallback(
    async (input: ManagedSkillCreateMutation | ManagedSkillMutation) => {
      if (!dialog || dialog.loading || !dialog.contentReady) return;
      const requestContextKey = contextKey;
      setBusy(true);
      setError(null);
      try {
        const client = new DesktopApiClient(config);
        let saved: ManagedSkill;
        if (dialog.skill) {
          const { full_content: fullContent, ...metadata } = input;
          saved = await client.updateManagedSkill(dialog.skill.id, metadata);
          if (fullContent)
            saved = await client.updateManagedSkillContent(dialog.skill.id, fullContent);
        } else {
          saved = await client.createManagedSkill(input as ManagedSkillCreateMutation);
        }
        if (contextKeyRef.current !== requestContextKey) return;
        setDialog(null);
        await onReload();
        onSaved(saved.id);
      } catch (caught) {
        if (contextKeyRef.current === requestContextKey) setError(errorMessage(caught));
      } finally {
        if (contextKeyRef.current === requestContextKey) setBusy(false);
      }
    },
    [config, contextKey, dialog, onReload, onSaved]
  );

  const remove = useCallback(async () => {
    if (!dialog?.skill || dialog.loading) return;
    const requestContextKey = contextKey;
    setBusy(true);
    setError(null);
    try {
      await new DesktopApiClient(config).deleteManagedSkill(dialog.skill.id);
      if (contextKeyRef.current !== requestContextKey) return;
      setDialog(null);
      onDeleted();
      await onReload();
    } catch (caught) {
      if (contextKeyRef.current === requestContextKey) setError(errorMessage(caught));
    } finally {
      if (contextKeyRef.current === requestContextKey) setBusy(false);
    }
  }, [config, contextKey, dialog, onDeleted, onReload]);

  return { dialog, busy, error, close, open, save, remove };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
