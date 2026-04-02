/**
 * Streaming tool preparation indicator components.
 * Shows a card for each tool currently being prepared by the agent.
 */

import { memo, useRef, useEffect } from 'react';

import { Loader2 } from 'lucide-react';

import { useAgentState, useActiveToolCalls } from '../../../stores/agent/executionStore';

export const StreamingToolPreparation: React.FC = memo(() => {
  const agentState = useAgentState();
  const activeToolCalls = useActiveToolCalls();

  if (agentState !== 'preparing') return null;

  const preparingTools = Array.from(activeToolCalls.entries()).filter(
    ([, call]) => call.status === 'preparing'
  );
  if (preparingTools.length === 0) return null;

  return (
    <>
      {preparingTools.map(([toolName, call]) => (
        <StreamingToolCard
          key={toolName}
          toolName={toolName}
          partialArguments={call.partialArguments}
        />
      ))}
    </>
  );
});
StreamingToolPreparation.displayName = 'StreamingToolPreparation';

const StreamingToolCard: React.FC<{ toolName: string; partialArguments?: string | undefined }> =
  memo(({ toolName, partialArguments }) => {
    const argsRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
      if (argsRef.current) {
        argsRef.current.scrollTop = argsRef.current.scrollHeight;
      }
    }, [partialArguments]);

    return (
      <div className="flex items-start gap-2 mb-2 animate-fade-in-up">
        <div className="flex flex-col items-center flex-shrink-0">
          <div className="w-6 h-6 rounded-full flex items-center justify-center border-2 border-blue-400 bg-blue-50 dark:bg-blue-950/50">
            <Loader2 size={11} className="text-blue-500 animate-spin motion-reduce:animate-none" />
          </div>
        </div>
        <div className="flex-1 min-w-0 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
          <div className="tool-prep-shimmer rounded-md border px-2.5 py-1.5 bg-blue-50 dark:bg-blue-950/30 border-blue-200 dark:border-blue-800/40">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-slate-700 dark:text-slate-300 flex-1 truncate">
                {toolName}
              </span>
               <div className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-blue-100 dark:bg-blue-500/10 text-blue-600 text-2xs font-bold uppercase tracking-wider">
                 <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse motion-reduce:animate-none" />
                 Preparing
               </div>
            </div>
            {partialArguments && (
              <div
                ref={argsRef}
                className="mt-1.5 px-2 py-1.5 bg-blue-50/50 dark:bg-blue-500/5 border border-blue-200/50 dark:border-blue-500/20 rounded text-xs-plus font-mono text-slate-600 dark:text-slate-400 overflow-x-auto max-h-24 overflow-y-auto"
              >
                <pre className="whitespace-pre-wrap break-words">
                  {partialArguments}
                  <span className="inline-block w-1.5 h-3 bg-blue-500 animate-pulse motion-reduce:animate-none ml-0.5 align-middle" />
                </pre>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  });
StreamingToolCard.displayName = 'StreamingToolCard';
