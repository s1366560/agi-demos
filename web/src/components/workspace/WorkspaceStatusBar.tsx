import React from 'react';

/**
 * Distilled from routa's `kanban-status-bar.tsx`. Each slot is independent and
 * hidden when its data is absent — the parent passes only what it knows.
 */

export type StatusTone = 'idle' | 'ok' | 'running' | 'warning' | 'error';

const TONE_DOT: Record<StatusTone, string> = {
  idle: 'bg-slate-300 dark:bg-slate-600',
  ok: 'bg-emerald-500',
  running: 'bg-sky-500 animate-pulse',
  warning: 'bg-amber-500',
  error: 'bg-rose-500',
};

export interface StatusSlotData {
  label: string;
  value: string;
  tone?: StatusTone;
  hint?: string;
}

export interface WorkspaceStatusBarProps {
  /** Currently active SubAgent, e.g. "@executor". */
  subAgent?: StatusSlotData;
  /** LLM provider + token usage summary, e.g. "gemini-2.5 · 12.4k". */
  llm?: StatusSlotData;
  /** Sandbox status, e.g. "ready" / "starting" / "errored". */
  sandbox?: StatusSlotData;
  /** Pending HITL count summary, e.g. "2 pending". */
  hitl?: StatusSlotData;
  /** Active skill chips count, e.g. "3 active". */
  skills?: StatusSlotData;
  /** Friction signal count for the last window, e.g. "5 / 7d". */
  friction?: StatusSlotData;
  className?: string;
}

interface SlotProps {
  data: StatusSlotData;
}

const Slot: React.FC<SlotProps> = ({ data }) => {
  const tone = data.tone ?? 'idle';
  return (
    <div
      className="flex items-center gap-1.5 px-2 py-1 rounded-md text-[12px] text-[#171717] dark:text-slate-200"
      title={data.hint ?? `${data.label}: ${data.value}`}
    >
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${TONE_DOT[tone]}`} />
      <span className="text-[#666] dark:text-slate-400">{data.label}</span>
      <span className="font-medium tabular-nums">{data.value}</span>
    </div>
  );
};

/**
 * A 1px-bordered, no-shadow status strip. Mount once at the bottom of a
 * workspace surface. Pass only the slots you have data for; missing slots
 * collapse silently.
 */
export const WorkspaceStatusBar: React.FC<WorkspaceStatusBarProps> = ({
  subAgent,
  llm,
  sandbox,
  hitl,
  skills,
  friction,
  className,
}) => {
  const slots: StatusSlotData[] = [];
  if (subAgent) slots.push(subAgent);
  if (llm) slots.push(llm);
  if (sandbox) slots.push(sandbox);
  if (hitl) slots.push(hitl);
  if (skills) slots.push(skills);
  if (friction) slots.push(friction);

  if (slots.length === 0) return null;

  return (
    <div
      role="status"
      aria-label="Workspace status"
      data-testid="workspace-status-bar"
      className={[
        'flex items-center gap-1 px-3 py-1.5',
        'border-t border-[rgba(0,0,0,0.08)] dark:border-slate-800',
        'bg-white dark:bg-surface-dark',
        'overflow-x-auto whitespace-nowrap',
        className ?? '',
      ]
        .join(' ')
        .trim()}
    >
      {slots.map((slot, idx) => (
        <React.Fragment key={`${slot.label}-${idx}`}>
          {idx > 0 && (
            <span aria-hidden="true" className="mx-1 text-[#cccccc] dark:text-slate-700">
              ·
            </span>
          )}
          <Slot data={slot} />
        </React.Fragment>
      ))}
    </div>
  );
};

export default WorkspaceStatusBar;
