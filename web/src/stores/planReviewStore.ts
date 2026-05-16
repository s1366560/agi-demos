/**
 * planReviewStore - Local acknowledgement state for work plans.
 *
 * Pure-frontend distillation of a "plan review gate": tracks per-conversation
 * which plan IDs the user has approved, requested changes for, or aborted. No
 * backend signal is required — this is a UX layer that adds an explicit
 * decision moment in front of an otherwise-passive `work_plan` event.
 *
 * Persisted to localStorage so the verdict survives reloads.
 */

import { create } from 'zustand';

export type PlanReviewVerdict = 'approved' | 'changes_requested' | 'aborted';

const STORAGE_KEY = 'memstack:planReview:v1';

interface PersistedShape {
  // conversationId -> planId -> verdict
  readonly verdicts: Record<string, Record<string, PlanReviewVerdict>>;
}

function loadFromStorage(): PersistedShape {
  if (typeof window === 'undefined') return { verdicts: {} };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { verdicts: {} };
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return { verdicts: {} };
    const v = (parsed as { verdicts?: unknown }).verdicts;
    if (!v || typeof v !== 'object') return { verdicts: {} };
    return { verdicts: v as Record<string, Record<string, PlanReviewVerdict>> };
  } catch {
    return { verdicts: {} };
  }
}

function saveToStorage(state: PersistedShape): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // ignore quota / private mode
  }
}

interface PlanReviewState {
  readonly verdicts: Readonly<Record<string, Readonly<Record<string, PlanReviewVerdict>>>>;
  setVerdict: (conversationId: string, planId: string, verdict: PlanReviewVerdict) => void;
  clearVerdict: (conversationId: string, planId: string) => void;
}

export const usePlanReviewStore = create<PlanReviewState>((set) => ({
  verdicts: loadFromStorage().verdicts,
  setVerdict: (conversationId, planId, verdict) => {
    set((prev) => {
      const convPrev = prev.verdicts[conversationId] ?? {};
      const next = {
        ...prev.verdicts,
        [conversationId]: { ...convPrev, [planId]: verdict },
      };
      saveToStorage({ verdicts: next });
      return { verdicts: next };
    });
  },
  clearVerdict: (conversationId, planId) => {
    set((prev) => {
      const convPrev = prev.verdicts[conversationId];
      if (!convPrev || !(planId in convPrev)) return prev;
      const { [planId]: _omit, ...restConv } = convPrev;
      void _omit;
      let nextConv: Record<string, Record<string, PlanReviewVerdict>>;
      if (Object.keys(restConv).length === 0) {
        const { [conversationId]: _removed, ...remaining } = prev.verdicts;
        void _removed;
        nextConv = remaining;
      } else {
        nextConv = { ...prev.verdicts, [conversationId]: restConv };
      }
      saveToStorage({ verdicts: nextConv });
      return { verdicts: nextConv };
    });
  },
}));

export function usePlanVerdict(
  conversationId: string | undefined | null,
  planId: string | undefined | null
): PlanReviewVerdict | undefined {
  return usePlanReviewStore((s) => {
    if (!conversationId || !planId) return undefined;
    return s.verdicts[conversationId]?.[planId];
  });
}
