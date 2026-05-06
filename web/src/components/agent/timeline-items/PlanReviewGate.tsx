/**
 * PlanReviewGate - Distilled "review gate" attached to a work_plan event.
 *
 * Adds an explicit decision moment (Approve / Request changes / Abort) on top
 * of the otherwise-passive WorkPlan card. Verdicts are persisted locally per
 * (conversationId, planId) via `usePlanReviewStore`.
 *
 * Side-effects on action:
 * - Approve: visual acknowledgement only (no backend call).
 * - Request changes: enqueues a follow-up prompt via `pendingPromptStore` so
 *   the user's revision request flushes after the agent yields. The textarea
 *   captures the requested changes inline.
 * - Abort: aborts the active stream via `useAgentV3Store.abortStream`.
 */

import { memo, useCallback, useState } from 'react';

import { Check, MessageSquarePlus, OctagonX, ChevronDown, ChevronRight } from 'lucide-react';

import { usePendingPromptStore } from '@/stores/pendingPromptStore';
import { usePlanReviewStore, usePlanVerdict, type PlanReviewVerdict } from '@/stores/planReviewStore';

import { useAgentV3Store } from '../../../stores/agentV3';

import type { WorkPlanTimelineEvent } from '../../../types/agent';

interface PlanReviewGateProps {
  conversationId: string | undefined;
  event: WorkPlanTimelineEvent;
}

const VERDICT_BADGE: Record<PlanReviewVerdict, { label: string; cls: string }> = {
  approved: {
    label: 'Approved',
    cls: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  },
  changes_requested: {
    label: 'Changes requested',
    cls: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  },
  aborted: {
    label: 'Aborted',
    cls: 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300',
  },
};

export const PlanReviewGate = memo(function PlanReviewGate({
  conversationId,
  event,
}: PlanReviewGateProps) {
  const planId = event.id;
  const verdict = usePlanVerdict(conversationId, planId);
  const setVerdict = usePlanReviewStore((s) => s.setVerdict);
  const clearVerdict = usePlanReviewStore((s) => s.clearVerdict);
  const enqueuePrompt = usePendingPromptStore((s) => s.enqueue);
  const abortStream = useAgentV3Store((s) => s.abortStream);

  const [showChangesInput, setShowChangesInput] = useState(false);
  const [changesText, setChangesText] = useState('');
  const [stepsExpanded, setStepsExpanded] = useState(false);

  const handleApprove = useCallback(() => {
    if (!conversationId) return;
    setVerdict(conversationId, planId, 'approved');
    setShowChangesInput(false);
  }, [conversationId, planId, setVerdict]);

  const handleAbort = useCallback(() => {
    if (!conversationId) return;
    abortStream(conversationId);
    setVerdict(conversationId, planId, 'aborted');
  }, [abortStream, conversationId, planId, setVerdict]);

  const handleSubmitChanges = useCallback(() => {
    if (!conversationId) return;
    const trimmed = changesText.trim();
    if (!trimmed) return;
    enqueuePrompt(conversationId, {
      text: `Please revise the plan based on this feedback:\n\n${trimmed}`,
    });
    setVerdict(conversationId, planId, 'changes_requested');
    setChangesText('');
    setShowChangesInput(false);
  }, [changesText, conversationId, enqueuePrompt, planId, setVerdict]);

  const handleReopen = useCallback(() => {
    if (!conversationId) return;
    clearVerdict(conversationId, planId);
  }, [clearVerdict, conversationId, planId]);

  const stepCount = event.steps.length;
  const Chevron = stepsExpanded ? ChevronDown : ChevronRight;

  if (!conversationId) return null;

  // Resolved state — show compact verdict pill with re-open option.
  if (verdict) {
    const badge = VERDICT_BADGE[verdict];
    return (
      <div
        data-testid="plan-review-gate-resolved"
        className="mt-2 flex items-center justify-between gap-2 rounded-md border border-slate-200/70 bg-slate-50/60 px-3 py-1.5 text-xs dark:border-slate-700/60 dark:bg-slate-800/40"
      >
        <span className={`rounded-full px-2 py-0.5 font-medium ${badge.cls}`}>{badge.label}</span>
        <button
          type="button"
          onClick={handleReopen}
          className="text-slate-500 underline-offset-2 hover:text-slate-700 hover:underline dark:text-slate-400 dark:hover:text-slate-200"
        >
          Re-open review
        </button>
      </div>
    );
  }

  return (
    <div
      data-testid="plan-review-gate"
      className="mt-2 overflow-hidden rounded-md border border-amber-200/70 bg-amber-50/40 dark:border-amber-700/50 dark:bg-amber-900/10"
    >
      <div className="flex items-center justify-between gap-2 border-b border-amber-200/60 px-3 py-1.5 dark:border-amber-700/40">
        <button
          type="button"
          onClick={() => {
            setStepsExpanded((v) => !v);
          }}
          className="flex items-center gap-1.5 text-xs font-medium text-amber-800 dark:text-amber-200"
          aria-expanded={stepsExpanded}
        >
          <Chevron size={12} />
          <span>Review gate</span>
          <span className="text-[10px] text-amber-600 dark:text-amber-300/70">
            {stepCount} {stepCount === 1 ? 'step' : 'steps'}
          </span>
        </button>
        <span className="text-[10px] text-amber-700/70 dark:text-amber-300/60">
          Approve to continue, or request changes
        </span>
      </div>

      {stepsExpanded ? (
        <ol className="space-y-1 border-b border-amber-200/40 px-3 py-2 text-xs text-slate-700 dark:border-amber-700/30 dark:text-slate-200">
          {event.steps.map((step) => (
            <li key={step.step_number} className="flex gap-2">
              <span className="w-5 flex-shrink-0 text-right font-mono text-amber-700/80 dark:text-amber-300/70">
                {step.step_number}.
              </span>
              <div className="min-w-0 flex-1">
                <div className="font-medium">{step.description}</div>
                {step.expected_output ? (
                  <div className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
                    → {step.expected_output}
                  </div>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      ) : null}

      {showChangesInput ? (
        <div className="space-y-2 px-3 py-2">
          <textarea
            value={changesText}
            onChange={(e) => {
              setChangesText(e.target.value);
            }}
            placeholder="What should change about the plan?"
            rows={3}
            className="w-full resize-y rounded border border-amber-200 bg-white px-2 py-1 text-xs text-slate-800 outline-none focus:border-amber-400 dark:border-amber-700/50 dark:bg-slate-900 dark:text-slate-100"
          />
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setShowChangesInput(false);
                setChangesText('');
              }}
              className="rounded px-2 py-1 text-xs text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSubmitChanges}
              disabled={changesText.trim().length === 0}
              className="rounded bg-amber-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Queue revision request
            </button>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-end gap-1.5 px-3 py-1.5">
          <button
            type="button"
            onClick={handleAbort}
            className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-rose-700 hover:bg-rose-100 dark:text-rose-300 dark:hover:bg-rose-900/30"
          >
            <OctagonX size={12} />
            Abort
          </button>
          <button
            type="button"
            onClick={() => {
              setShowChangesInput(true);
            }}
            className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-amber-700 hover:bg-amber-100 dark:text-amber-200 dark:hover:bg-amber-900/30"
          >
            <MessageSquarePlus size={12} />
            Request changes
          </button>
          <button
            type="button"
            onClick={handleApprove}
            className="inline-flex items-center gap-1 rounded bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-emerald-700"
          >
            <Check size={12} />
            Approve
          </button>
        </div>
      )}
    </div>
  );
});
