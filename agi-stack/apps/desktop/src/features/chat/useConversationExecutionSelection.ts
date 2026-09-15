import { useCallback, useEffect, useRef, useState } from "react";
import type { AgentConversation, ComposerContextItem } from "../../types";
import {
  requireExecutionSelection,
  type ConversationExecutionSelection,
} from "../../plugins/desktopConversationSelectionContractV2";
import type { ComposerCatalogClient } from "./composerCatalogModel";
import { appendComposerContextItem } from "./chatComposerModel";

const slots = {
  agent: "agent_id",
  skill: "forced_skill_id",
  subagent: "subagent_id",
} as const;
export function isExecutionContext(item: ComposerContextItem): boolean {
  return (
    typeof item.metadata?.execution_slot === "string" &&
    Object.hasOwn(slots, item.metadata.execution_slot)
  );
}
export function mergeExecutionSelectionItems(
  current: ComposerContextItem[],
  persisted: ComposerContextItem[],
): ComposerContextItem[] {
  return current
    .filter((item) => item.metadata?.authoritative_selection !== true)
    .reduce((items, item) => {
      if (
        items.some(
          (saved) =>
            saved.kind === item.kind && saved.resource_id === item.resource_id,
        )
      )
        return items;
      return appendComposerContextItem(items, item);
    }, persisted);
}

export function useConversationExecutionSelection({
  api,
  conversation,
  enabled,
  sending,
  onResolved,
}: {
  api: ComposerCatalogClient;
  conversation: AgentConversation | null;
  enabled: boolean;
  sending: boolean;
  onResolved: (items: ComposerContextItem[]) => void;
}) {
  const [loadedId, setLoadedId] = useState<string | null>(null);
  const [pendingOperation, setPendingOperation] = useState<{
    conversationId: string;
    token: number;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const current = useRef(conversation);
  current.current = conversation;
  const selection = useRef<ConversationExecutionSelection | null>(null);
  const sequence = useRef(0);
  const id = conversation?.id ?? "";
  const pending = pendingOperation?.conversationId === id;
  const accept = useCallback(
    async (value: AgentConversation, expectedSequence: number) => {
      const selected = requireExecutionSelection(value);
      const labels = await Promise.allSettled([
        selected.agent_id ? api.listManagedAgents() : Promise.resolve([]),
        selected.forced_skill_id
          ? api.listManagedSkills()
          : Promise.resolve([]),
        selected.subagent_id ? api.listManagedSubAgents() : Promise.resolve([]),
      ]);
      if (
        sequence.current !== expectedSequence ||
        current.current?.id !== value.id
      )
        return;
      const items: ComposerContextItem[] = [];
      for (const [index, kind] of (
        ["agent", "skill", "subagent"] as const
      ).entries()) {
        const resourceId = selected[slots[kind]];
        if (!resourceId) continue;
        const result = labels[index];
        const records =
          result?.status === "fulfilled"
            ? (result.value as unknown as Record<string, unknown>[])
            : [];
        const resource = records.find(
          (entry) => entry.id === resourceId || entry.name === resourceId,
        );
        const label = resource?.display_name ?? resource?.name ?? resourceId;
        items.push({
          kind: kind === "subagent" ? "agent" : kind,
          resource_id: resourceId,
          label: typeof label === "string" ? label : resourceId,
          metadata: {
            execution_slot: kind,
            authoritative_selection: true,
            ...(kind === "agent" ? { execution_agent_id: resourceId } : {}),
            ...(kind === "skill" ? { execution_skill_name: resourceId } : {}),
          },
        });
      }
      selection.current = selected;
      setLoadedId(value.id);
      setError(null);
      onResolved(items);
    },
    [api, onResolved],
  );
  const refresh = useCallback(async () => {
    const target = current.current;
    if (!enabled || !target) return;
    const token = ++sequence.current;
    try {
      if (!api.readExecutionSelection)
        throw new Error("Execution selection authority is unavailable");
      await accept(await api.readExecutionSelection(target), token);
    } catch (failure) {
      if (sequence.current === token)
        setError(failure instanceof Error ? failure.message : String(failure));
    }
  }, [api, enabled, accept]);
  useEffect(() => {
    if (!sending) void refresh();
    return () => {
      sequence.current += 1;
    };
  }, [id, sending, refresh]);
  const remove = useCallback(
    async (item: ComposerContextItem): Promise<boolean> => {
      if (!enabled || !isExecutionContext(item)) return true;
      const target = current.current;
      const kind = item.metadata?.execution_slot as keyof typeof slots;
      if (!target || loadedId !== target.id || pending) return false;
      if (!selection.current?.[slots[kind]]) return true;
      const token = ++sequence.current;
      setPendingOperation({ conversationId: target.id, token });
      try {
        if (!api.updateExecutionSelection)
          throw new Error("Execution selection authority is unavailable");
        const updated = await api.updateExecutionSelection(target, {
          [slots[kind]]: null,
        });
        await accept(updated, token);
        return sequence.current === token && current.current?.id === target.id;
      } catch (failure) {
        if (sequence.current === token)
          setError(
            failure instanceof Error ? failure.message : String(failure),
          );
        return false;
      } finally {
        setPendingOperation((operation) =>
          operation?.token === token ? null : operation,
        );
      }
    },
    [enabled, loadedId, pending, api, accept],
  );
  return {
    ready: !enabled || loadedId === id,
    pending,
    error,
    refresh,
    remove,
  };
}
