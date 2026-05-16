import React from 'react';

import {
  RefreshCw,
  Copy,
  Eraser,
  Users,
  Download,
  Cpu,
  Wrench,
  Loader2,
  type LucideIcon,
} from 'lucide-react';

interface MaintenanceOperationProps {
  title: string;
  description: React.ReactNode;
  icon: string;
  actionLabel: string;
  secondaryActionLabel?: string | undefined;
  onAction: () => void;
  onSecondaryAction?: (() => void) | undefined;
  loading?: boolean | undefined;
  warning?: boolean | undefined;
}

const iconMap: Record<string, LucideIcon> = {
  refresh: RefreshCw,
  content_copy: Copy,
  cleaning_services: Eraser,
  group_work: Users,
  download: Download,
  model_training: Cpu,
};

export const MaintenanceOperation: React.FC<MaintenanceOperationProps> = ({
  title,
  description,
  icon,
  actionLabel,
  secondaryActionLabel,
  onAction,
  onSecondaryAction,
  loading = false,
  warning = false,
}) => {
  const IconComponent = iconMap[icon] || Wrench;

  return (
    <div className="flex flex-col gap-4 p-4 transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/50 sm:p-6 md:flex-row md:items-center md:justify-between">
      <div className="flex min-w-0 items-start gap-3 sm:gap-4">
        <div
          className={`shrink-0 rounded-lg p-3 ${warning ? 'bg-yellow-50 text-yellow-600 dark:bg-yellow-900/20 dark:text-yellow-400' : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400'}`}
        >
          <IconComponent size={24} />
        </div>
        <div className="min-w-0">
          <h3 className="font-medium text-slate-900 dark:text-white">{title}</h3>
          <div className="mt-1 max-w-lg break-words text-sm text-slate-500 dark:text-slate-400">
            {description}
          </div>
        </div>
      </div>
      <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:justify-end sm:gap-3">
        {onSecondaryAction && (
          <button
            type="button"
            onClick={onSecondaryAction}
            disabled={loading}
            className="min-h-10 flex-1 rounded-lg px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-100 disabled:opacity-50 dark:text-slate-300 dark:hover:bg-slate-800 sm:flex-none"
          >
            {secondaryActionLabel}
          </button>
        )}
        <button
          type="button"
          onClick={onAction}
          disabled={loading}
          className={`flex min-h-10 flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-white transition-colors disabled:opacity-50 sm:flex-none ${warning ? 'bg-yellow-600 hover:bg-yellow-700' : 'bg-primary hover:bg-primary/90'}`}
        >
          {loading && <Loader2 size={14} className="animate-spin motion-reduce:animate-none" />}
          {actionLabel}
        </button>
      </div>
    </div>
  );
};
