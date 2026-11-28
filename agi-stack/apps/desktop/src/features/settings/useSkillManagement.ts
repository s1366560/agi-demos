import { useCallback, useEffect, useRef, useState } from 'react';

import type { DesktopTenantSkillDefinitionsClientV2 } from '../../plugins/desktopTenantSkillDefinitionsAuthorityModuleV2';
import type {
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
  client,
  contextKey,
  canCreate,
  onReload,
  onSaved,
  onDeleted,
}: {
  active: boolean;
  client: DesktopTenantSkillDefinitionsClientV2;
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
        const content = await client.getManagedSkillContent(skill.id);
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
    [canCreate, client, contextKey]
  );

  const save = useCallback(
    async (input: ManagedSkillCreateMutation | ManagedSkillMutation) => {
      if (!dialog || dialog.loading || !dialog.contentReady) return;
      const requestContextKey = contextKey;
      setBusy(true);
      setError(null);
      try {
        let saved: ManagedSkill;
        if (dialog.skill) {
          const { full_content: fullContent, ...metadata } = input;
          saved = await client.updateManagedSkill(
            dialog.skill.id,
            metadata,
            dialog.skill.revision,
          );
          if (fullContent)
            saved = await client.updateManagedSkillContent(
              dialog.skill.id,
              fullContent,
              saved.revision,
            );
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
    [client, contextKey, dialog, onReload, onSaved]
  );

  const remove = useCallback(async () => {
    if (!dialog?.skill || dialog.loading) return;
    const requestContextKey = contextKey;
    setBusy(true);
    setError(null);
    try {
      await client.deleteManagedSkill(
        dialog.skill.id,
        dialog.skill.revision,
      );
      if (contextKeyRef.current !== requestContextKey) return;
      setDialog(null);
      onDeleted();
      await onReload();
    } catch (caught) {
      if (contextKeyRef.current === requestContextKey) setError(errorMessage(caught));
    } finally {
      if (contextKeyRef.current === requestContextKey) setBusy(false);
    }
  }, [client, contextKey, dialog, onDeleted, onReload]);

  return { dialog, busy, error, close, open, save, remove };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
