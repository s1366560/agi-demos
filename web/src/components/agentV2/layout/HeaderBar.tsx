/**
 * Header Bar
 *
 * Top navigation bar with project info, status, and actions.
 */

import { useParams, useNavigate } from 'react-router-dom';
import {
  SettingOutlined,
  ArrowLeftOutlined,
  MenuOutlined,
} from '@ant-design/icons';
import { useAgentV2Store } from '../../../stores/agentV2';

interface HeaderBarProps {
  onToggleSidebar?: () => void;
}

export function HeaderBar({ onToggleSidebar }: HeaderBarProps) {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const {
    isStreaming,
    streamingPhase,
    totalTokens,
    totalCost,
    currentConversation,
  } = useAgentV2Store();

  const phaseLabel = {
    idle: 'Ready',
    thinking: 'Thinking...',
    planning: 'Planning...',
    executing: 'Executing...',
    responding: 'Responding...',
  };

  const phaseColor = {
    idle: 'text-gray-500',
    thinking: 'text-purple-600 dark:text-purple-400',
    planning: 'text-blue-600 dark:text-blue-400',
    executing: 'text-orange-600 dark:text-orange-400',
    responding: 'text-green-600 dark:text-green-400',
  };

  return (
    <header className="h-14 flex items-center justify-between px-4 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
      {/* Left - Back & Sidebar Toggle */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => navigate(-1)}
          className="p-2 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
          title="Go back"
        >
          <ArrowLeftOutlined />
        </button>

        {onToggleSidebar && (
          <button
            onClick={onToggleSidebar}
            className="p-2 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
            title="Toggle sidebar"
          >
            <MenuOutlined />
          </button>
        )}

        {/* Conversation Title */}
        <div className="ml-2">
          <h1 className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate max-w-md">
            {currentConversation?.title || 'Agent Chat'}
          </h1>
        </div>
      </div>

      {/* Center - Status Indicator */}
      <div className="flex items-center gap-3">
        {isStreaming && (
          <div className="flex items-center gap-2">
            <span className="flex gap-0.5">
              <span className={`w-1.5 h-1.5 rounded-full bg-current ${phaseColor[streamingPhase]} animate-pulse`} />
              <span className={`w-1.5 h-1.5 rounded-full bg-current ${phaseColor[streamingPhase]} animate-pulse delay-75`} />
              <span className={`w-1.5 h-1.5 rounded-full bg-current ${phaseColor[streamingPhase]} animate-pulse delay-150`} />
            </span>
            <span className={`text-sm font-medium ${phaseColor[streamingPhase]}`}>
              {phaseLabel[streamingPhase]}
            </span>
          </div>
        )}
      </div>

      {/* Right - Cost Stats & Settings */}
      <div className="flex items-center gap-4">
        {/* Token & Cost */}
        {(totalTokens > 0 || totalCost > 0) && (
          <div className="hidden sm:flex items-center gap-3 text-xs text-gray-500 dark:text-gray-400">
            <span>{totalTokens.toLocaleString()} tokens</span>
            <span>·</span>
            <span>${totalCost.toFixed(4)}</span>
          </div>
        )}

        {/* Settings */}
        <button
          onClick={() => navigate(`/project/${projectId}/settings`)}
          className="p-2 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
          title="Settings"
        >
          <SettingOutlined />
        </button>
      </div>
    </header>
  );
}
