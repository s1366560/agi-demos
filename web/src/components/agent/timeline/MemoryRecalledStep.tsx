/**
 * Memory recalled timeline step component.
 *
 * Displays recalled memories in a collapsible panel within the
 * ExecutionTimeline. Shows count, search time, and individual
 * memory items with category and source labels.
 */

import React, { useState } from 'react';

import { ChevronDown, ChevronRight, Database } from 'lucide-react';

import type {
  MemoryRecalledTimelineEvent,
  MemoryCapturedTimelineEvent,
} from '../../../types/agent';

interface MemoryRecalledStepProps {
  event: MemoryRecalledTimelineEvent;
}

export const MemoryRecalledStep: React.FC<MemoryRecalledStepProps> = ({ event }) => {
  const [expanded, setExpanded] = useState(false);

  if (!event.memories || event.memories.length === 0) {
    return null;
  }

  return (
    <div className="my-1 rounded-md border border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950/30">
      <button
        onClick={() => {
          setExpanded(!expanded);
        }}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-blue-700 dark:text-blue-300"
      >
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <Database size={12} />
        <span>
          Recalled {event.count} {event.count === 1 ? 'memory' : 'memories'}
        </span>
        <span className="text-blue-500 dark:text-blue-400">({event.searchMs}ms)</span>
      </button>
      {expanded && (
        <div className="border-t border-blue-200 px-3 py-2 dark:border-blue-800">
          <ul className="space-y-1">
            {event.memories.map((mem, idx) => (
              <li key={idx} className="text-xs text-gray-700 dark:text-gray-300">
                <span className="mr-1 rounded bg-blue-100 px-1 py-0.5 text-[10px] font-medium text-blue-600 dark:bg-blue-900 dark:text-blue-400">
                  {mem.category}
                </span>
                <span className="text-gray-400">|</span>
                <span className="ml-1 text-gray-500">{mem.source}</span>
                <span className="text-gray-400"> - </span>
                <span className="break-words">
                  {mem.content.length > 200 ? `${mem.content.slice(0, 200)}...` : mem.content}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

interface MemoryCapturedStepProps {
  event: MemoryCapturedTimelineEvent;
}

export const MemoryCapturedStep: React.FC<MemoryCapturedStepProps> = ({ event }) => {
  if (!event.capturedCount || event.capturedCount === 0) {
    return null;
  }

  return (
    <div className="my-1 flex items-center gap-2 rounded-md border border-green-200 bg-green-50 px-3 py-1.5 text-xs text-green-700 dark:border-green-800 dark:bg-green-950/30 dark:text-green-300">
      <Database size={12} />
      <span>
        Captured {event.capturedCount} {event.capturedCount === 1 ? 'memory' : 'memories'}
      </span>
      {event.categories.length > 0 && (
        <span className="text-green-500 dark:text-green-400">({event.categories.join(', ')})</span>
      )}
    </div>
  );
};
