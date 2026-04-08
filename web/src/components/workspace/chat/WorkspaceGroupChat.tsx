import React from 'react';

import { useTranslation } from 'react-i18next';

import { ArrowLeft, Users } from 'lucide-react';

import { ChatPanel } from './ChatPanel';

export interface WorkspaceGroupChatProps {
  tenantId: string;
  projectId: string;
  workspaceId: string;
  onBack: () => void;
}

export const WorkspaceGroupChat: React.FC<WorkspaceGroupChatProps> = ({
  tenantId,
  projectId,
  workspaceId,
  onBack,
}) => {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col h-full w-full overflow-hidden bg-white dark:bg-slate-900">
      {/* Header */}
      <div className="flex-shrink-0 flex items-center gap-3 px-4 py-3 border-b border-slate-200/60 dark:border-slate-700/50 bg-slate-50 dark:bg-slate-800/80">
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-sm text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          {t('common.back', 'Back')}
        </button>
        <div className="flex items-center gap-2">
          <div className="flex items-center justify-center h-8 w-8 rounded-lg bg-indigo-100 dark:bg-indigo-900/50">
            <Users className="h-4 w-4 text-indigo-600 dark:text-indigo-400" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              {t('agent.groupChat', 'Workspace Chat')}
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {t('agent.groupChat.subtitle', 'Collaborate with team members and agents')}
            </p>
          </div>
        </div>
      </div>
      {/* Chat content */}
      <div className="flex-1 overflow-hidden">
        <ChatPanel tenantId={tenantId} projectId={projectId} workspaceId={workspaceId} />
      </div>
    </div>
  );
};
