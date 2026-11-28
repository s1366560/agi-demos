import { useState, type ReactNode } from 'react';
import { GripHorizontal } from 'lucide-react';
import { Resizer } from '@/components/layout/Resizer';

interface ChatColumnProps {
  header?: ReactNode;
  identity?: ReactNode;
  timeline: ReactNode;
  placement: ReactNode;
  composer: ReactNode;
}

/** The original chat column, shared by compatibility and signed command transports. */
export function AgentChatColumn({
  header,
  identity,
  timeline,
  placement,
  composer,
}: ChatColumnProps) {
  const [inputHeight, setInputHeight] = useState(160);
  return (
    <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden relative">
      {header && (
        <div className="flex-shrink-0 min-h-12 border-b border-slate-200/60 dark:border-slate-700/50 bg-white dark:bg-slate-900 px-4 py-2 flex items-center gap-2">
          {header}
        </div>
      )}
      {identity && (
        <div className="flex-shrink-0 border-b border-slate-200/60 dark:border-slate-700/50 bg-white/60 dark:bg-slate-900/40 px-4 py-2 flex items-center gap-2 min-w-0">
          {identity}
        </div>
      )}
      <div className="flex-1 overflow-hidden relative min-h-0">{timeline}</div>
      <div
        className="relative flex flex-shrink-0 flex-col border-t border-slate-200/60 bg-white shadow-[0_-1px_2px_rgba(15,23,42,0.025)] dark:border-slate-700/50 dark:bg-slate-900"
        style={{ minHeight: inputHeight }}
      >
        <div className="absolute -top-2 left-0 right-0 z-20 flex justify-center">
          <Resizer
            direction="vertical"
            currentSize={inputHeight}
            minSize={160}
            maxSize={560}
            onResize={setInputHeight}
            position="top"
          />
          <div className="pointer-events-none absolute top-1 flex items-center gap-1 text-slate-400">
            <GripHorizontal size={12} />
          </div>
        </div>
        <div className="px-4 pt-3">{placement}</div>
        {composer}
      </div>
    </div>
  );
}

export function AgentStatusFrame({
  slots,
  status,
  actions,
}: {
  slots?: ReactNode;
  status?: ReactNode;
  actions: ReactNode;
}) {
  return (
    <div className="flex-shrink-0 border-t border-slate-200/60 dark:border-slate-700/50 bg-slate-50 dark:bg-slate-800/80 min-w-0">
      <div className="flex items-center min-w-0 min-h-8">
        {slots}
        <div className="flex-1 min-w-0 overflow-hidden">{status}</div>
        <div className="flex items-center gap-1 sm:gap-2 pr-2 sm:pr-3 flex-shrink-0">{actions}</div>
      </div>
    </div>
  );
}
