import React from 'react';

import { RefreshCw, Copy, Eraser, Users, Download, Cpu, Wrench, Loader2, type LucideIcon } from 'lucide-react';

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
    <div className="flex items-center justify-between p-6 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors">
      <div className="flex items-start gap-4">
        <div
          className={`p-3 rounded-lg ${warning ? 'bg-yellow-50 dark:bg-yellow-900/20 text-yellow-600 dark:text-yellow-400' : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400'}`}
        >
          <IconComponent size={24} />
        </div>
        <div>
          <h3 className="font-medium text-slate-900 dark:text-white">{title}</h3>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1 max-w-lg">{description}</p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        {onSecondaryAction && (
          <button
            type="button"
            onClick={onSecondaryAction}
            disabled={loading}
            className="px-4 py-2 text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors disabled:opacity-50"
          >
            {secondaryActionLabel}
          </button>
        )}
        <button
          type="button"
          onClick={onAction}
          disabled={loading}
          className={`px-4 py-2 text-sm font-medium text-white rounded-lg transition-colors flex items-center gap-2 disabled:opacity-50 ${warning ? 'bg-yellow-600 hover:bg-yellow-700' : 'bg-primary hover:bg-primary/90'}`}
        >
          {loading && (
            <Loader2 size={14} className="animate-spin motion-reduce:animate-none" />
          )}
          {actionLabel}
        </button>
      </div>
    </div>
  );
};
