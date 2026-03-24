import type React from 'react';
import { useState, useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import { StopCircle, RotateCcw, Send, X } from 'lucide-react';

import { agentService } from '@/services/agentService';

interface SubAgentActionsProps {
  subagentId: string;
  conversationId: string;
}

export const SubAgentActions: React.FC<SubAgentActionsProps> = ({ subagentId, conversationId }) => {
  const { t } = useTranslation();
  const [showRedirect, setShowRedirect] = useState(false);
  const [instruction, setInstruction] = useState('');

  const handleStop = useCallback(() => {
    agentService.killSubAgent(conversationId, subagentId);
  }, [conversationId, subagentId]);

  const handleRedirect = useCallback(() => {
    if (instruction.trim()) {
      agentService.steerSubAgent(conversationId, subagentId, instruction.trim());
      setInstruction('');
      setShowRedirect(false);
    }
  }, [conversationId, subagentId, instruction]);

  return (
    <div className="mt-2 flex flex-col gap-2 animate-fade-in">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handleStop}
          className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md hover:bg-red-100 dark:hover:bg-red-900/40 transition-colors"
          title={t('agent.subagent.action_stop')}
        >
          <StopCircle className="w-3.5 h-3.5" />
          {t('agent.subagent.action_stop')}
        </button>
        <button
          type="button"
          onClick={() => {
            setShowRedirect(!showRedirect);
          }}
          className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-md hover:bg-amber-100 dark:hover:bg-amber-900/40 transition-colors"
          title={t('agent.subagent.action_redirect')}
        >
          <RotateCcw className="w-3.5 h-3.5" />
          {t('agent.subagent.action_redirect')}
        </button>
      </div>
      {showRedirect && (
        <div className="flex items-center gap-1.5 animate-fade-in">
          <input
            type="text"
            value={instruction}
            onChange={(e) => {
              setInstruction(e.target.value);
            }}
            onKeyDown={(e) => e.key === 'Enter' && handleRedirect()}
            placeholder={t('agent.subagent.redirect_placeholder')}
            aria-label={t('agent.subagent.redirect_placeholder')}
            className="flex-1 px-2.5 py-1.5 text-xs border border-gray-200 dark:border-gray-700 rounded-md bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-amber-500 focus:border-amber-500"
          />
          <button
            type="button"
            onClick={handleRedirect}
            disabled={!instruction.trim()}
            aria-label={t('agent.subagent.send_redirect', 'Send redirect')}
            className="inline-flex items-center p-1.5 text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-900/30 rounded-md disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <Send className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => {
              setShowRedirect(false);
              setInstruction('');
            }}
            aria-label={t('agent.subagent.cancel_redirect', 'Cancel redirect')}
            className="inline-flex items-center p-1.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-md transition-colors"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </div>
  );
};
