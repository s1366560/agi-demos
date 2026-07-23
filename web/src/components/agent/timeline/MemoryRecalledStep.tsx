/**
 * Memory captured timeline step component.
 *
 * Displays the count of memories captured during execution as a
 * compact inline row within the ExecutionTimeline.
 */

import type React from 'react';

import { useTranslation } from 'react-i18next';

import { Database } from 'lucide-react';

import type { MemoryCapturedTimelineEvent } from '../../../types/agent';

interface MemoryCapturedStepProps {
  event: MemoryCapturedTimelineEvent;
}

export const MemoryCapturedStep: React.FC<MemoryCapturedStepProps> = ({ event }) => {
  const { t } = useTranslation();

  if (!event.capturedCount || event.capturedCount === 0) {
    return null;
  }

  return (
    <div className="py-1 flex items-center gap-2 rounded-md border border-green-200 bg-green-50 px-3 py-1.5 text-xs text-green-700 dark:border-green-800 dark:bg-green-950/30 dark:text-green-300">
      <Database size={12} />
      <span>
        {t('components.memoryTimeline.captured', {
          defaultValue: 'Captured {{count}} memories',
          count: event.capturedCount,
        })}
      </span>
      {event.categories.length > 0 && (
        <span className="text-green-500 dark:text-green-400">({event.categories.join(', ')})</span>
      )}
    </div>
  );
};
