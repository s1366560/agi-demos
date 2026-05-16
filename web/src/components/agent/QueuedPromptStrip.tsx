/**
 * QueuedPromptStrip — pill row above the textarea showing prompts the user
 * queued while the agent was still streaming. Each pill can be removed; the
 * head of the queue is dispatched automatically by InputBar once streaming
 * ends.
 */

import { memo } from 'react';

import { useTranslation } from 'react-i18next';

import { Clock, X } from 'lucide-react';

import {
  usePendingPrompts,
  usePendingPromptStore,
  type PendingPrompt,
} from '@/stores/pendingPromptStore';

import type { TFunction } from 'i18next';

interface QueuedPromptStripProps {
  conversationId: string | undefined;
  isStreaming: boolean;
}

function tFallback(t: TFunction, key: string, fallback: string): string {
  const translated = t(key, fallback);
  return translated === key ? fallback : translated;
}

const Pill = memo<{
  prompt: PendingPrompt;
  isHead: boolean;
  isStreaming: boolean;
  onRemove: () => void;
}>(({ prompt, isHead, isStreaming, onRemove }) => {
  const { t } = useTranslation();
  const preview = prompt.text.length > 60 ? `${prompt.text.slice(0, 60).trim()}…` : prompt.text;
  return (
    <div
      className={`group inline-flex max-w-full items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] ${
        isHead && isStreaming
          ? 'border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-700/60 dark:bg-blue-950/30 dark:text-blue-300'
          : 'border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700/60 dark:bg-slate-800/40 dark:text-slate-200'
      }`}
      title={prompt.text}
    >
      <Clock size={10} className="shrink-0 opacity-70" />
      <span className="truncate">{preview}</span>
      {prompt.skillName ? (
        <span className="shrink-0 rounded bg-white/70 px-1 font-mono text-[9px] text-slate-500 dark:bg-slate-900/70 dark:text-slate-400">
          /{prompt.skillName}
        </span>
      ) : null}
      {prompt.subAgentName ? (
        <span className="shrink-0 rounded bg-white/70 px-1 font-mono text-[9px] text-slate-500 dark:bg-slate-900/70 dark:text-slate-400">
          @{prompt.subAgentName}
        </span>
      ) : null}
      <button
        type="button"
        onClick={onRemove}
        className="shrink-0 rounded-full p-0.5 text-current opacity-60 transition-opacity hover:bg-black/5 hover:opacity-100 dark:hover:bg-white/10"
        aria-label={tFallback(t, 'agent.queuedPrompt.remove', 'Remove queued prompt')}
      >
        <X size={10} />
      </button>
    </div>
  );
});
Pill.displayName = 'QueuedPromptPill';

export const QueuedPromptStrip = memo<QueuedPromptStripProps>(({ conversationId, isStreaming }) => {
  const { t } = useTranslation();
  const queue = usePendingPrompts(conversationId);
  const remove = usePendingPromptStore((state) => state.remove);

  if (!conversationId || queue.length === 0) return null;

  return (
    <div
      className="flex flex-wrap items-center gap-1 px-3 pb-1 pt-2"
      data-testid="queued-prompt-strip"
    >
      <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400 dark:text-slate-500">
        {t('agent.queuedPrompt.count', {
          defaultValue: 'Queued · {{count}}',
          count: queue.length,
        })}
      </span>
      {queue.map((prompt, idx) => (
        <Pill
          key={prompt.id}
          prompt={prompt}
          isHead={idx === 0}
          isStreaming={isStreaming}
          onRemove={() => {
            remove(conversationId, prompt.id);
          }}
        />
      ))}
    </div>
  );
});
QueuedPromptStrip.displayName = 'QueuedPromptStrip';

export default QueuedPromptStrip;
