/**
 * ConversationSidebar - Modern conversation list sidebar
 * 
 * Features:
 * - Shows all conversations with status indicators
 * - HITL (Human-In-The-Loop) pending indicators for conversations awaiting user input
 * - Streaming indicators for active conversations
 */

import type { FC } from 'react';
import { useMemo, useState, memo, useTransition } from 'react';

import { 
  Plus, 
  MessageSquare, 
  MoreVertical, 
  Trash2, 
  Edit3,
  Bot,
  AlertCircle,
  Loader2,
  PanelLeft,
  PanelLeftClose
} from 'lucide-react';

import { LazyButton, LazyBadge, LazyTooltip, LazyDropdown, LazyModal, LazyInput } from '@/components/ui/lazyAntd';

import { formatDistanceToNow } from '../../utils/date';

import type { Conversation } from '../../types/agent';
import type { HITLSummary } from '../../types/conversationState';
import type { MenuProps } from 'antd';


/**
 * Conversation status for UI display
 */
export interface ConversationStatus {
  /** Whether this conversation is currently streaming */
  isStreaming: boolean;
  /** Pending HITL request summary (if any) */
  pendingHITL: HITLSummary | null;
}

interface ConversationSidebarProps {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string, e: React.MouseEvent) => void;
  onRename?: (id: string, title: string) => Promise<void>;
  collapsed: boolean;
  onToggleCollapse: () => void;
  headerExtra?: React.ReactNode;
  /** Status map for each conversation (conversationId -> status) */
  conversationStatuses?: Map<string, ConversationStatus>;
}

interface ConversationItemProps {
  conversation: Conversation;
  isActive: boolean;
  onSelect: () => void;
  onDelete: (e: React.MouseEvent) => void;
  onRename?: () => void;
  compact?: boolean;
  /** Status for this conversation */
  status?: ConversationStatus;
}

// Memoized ConversationItem to prevent unnecessary re-renders (rerender-memo)
const ConversationItem = memo<ConversationItemProps>(({
  conversation,
  isActive,
  onSelect,
  onDelete,
  onRename,
  compact = false,
  status,
}) => {
  const timeAgo = useMemo(() => {
    try {
      return formatDistanceToNow(new Date(conversation.created_at));
    } catch {
      return '';
    }
  }, [conversation.created_at]);

  const handleMenuClick: MenuProps['onClick'] = ({ key }) => {
    if (key === 'delete') {
      onDelete({} as React.MouseEvent);
    } else if (key === 'rename' && onRename) {
      onRename();
    }
  };

  const items: MenuProps['items'] = useMemo(() => [
    {
      key: 'rename',
      icon: <Edit3 size={14} />,
      label: 'Rename',
      onClick: () => onRename?.(),
    },
    {
      key: 'delete',
      icon: <Trash2 size={14} />,
      label: 'Delete',
      danger: true,
      onClick: (e) => onDelete(e.domEvent as React.MouseEvent),
    },
  ], [onDelete, onRename]);

  // Determine status indicator
  const hasHITL = status?.pendingHITL != null;
  const isStreaming = status?.isStreaming ?? false;

  if (compact) {
    return (
      <LazyTooltip
        title={
          <div>
            <div>{conversation.title || 'Untitled'}</div>
            {hasHITL && <div className="text-amber-400 text-xs mt-1">⚠️ Needs your input</div>}
            {isStreaming && <div className="text-blue-400 text-xs mt-1">🔄 Processing...</div>}
          </div>
        }
        placement="right"
      >
        <button
          type="button"
          onClick={onSelect}
          className={`
            w-full p-3 rounded-xl mb-1 transition-all duration-200
            flex items-center justify-center relative
            ${isActive 
              ? 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200' 
              : 'text-slate-500 hover:bg-slate-50 dark:hover:bg-slate-800/60'
            }
          `}
        >
          <MessageSquare size={20} />
          {isActive && (
            <span className="absolute left-0 w-0.5 h-5 bg-slate-400 dark:bg-slate-500 rounded-r-full" />
          )}
          {/* HITL indicator badge */}
          {hasHITL && (
            <span className="absolute -top-1 -right-1 w-3 h-3 bg-amber-500 rounded-full animate-pulse" />
          )}
          {/* Streaming indicator */}
          {!hasHITL && isStreaming && (
            <span className="absolute -top-1 -right-1 w-3 h-3 bg-blue-500 rounded-full animate-pulse" />
          )}
        </button>
      </LazyTooltip>
    );
  }

  return (
    <button
      type="button"
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect();
        }
      }}
      className={`
        w-full text-left group relative p-3 rounded-xl mb-1 cursor-pointer
        transition-all duration-200 border
        ${isActive 
          ? 'bg-slate-50 dark:bg-slate-800/60 border-slate-200 dark:border-slate-700 text-slate-900 dark:text-slate-100' 
          : 'bg-transparent border-transparent text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/40'
        }
        ${hasHITL ? 'border-amber-300 dark:border-amber-600/50' : ''}
      `}
    >
      <div className="flex items-start gap-3">
        {/* Icon with status indicator */}
        <div className={`
          relative w-9 h-9 rounded-lg flex items-center justify-center shrink-0
          ${hasHITL 
            ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400'
            : isActive 
              ? 'bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300' 
              : 'bg-slate-100 dark:bg-slate-800 text-slate-500'
          }
        `}>
          {hasHITL ? (
            <AlertCircle size={18} className="animate-pulse" />
          ) : isStreaming ? (
            <Loader2 size={18} className="animate-spin" />
          ) : (
            <MessageSquare size={18} />
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <p className="font-medium text-sm truncate">
              {conversation.title || 'Untitled Conversation'}
            </p>
            {/* Status badge */}
            {hasHITL ? (
              <LazyTooltip title={status?.pendingHITL?.title || 'Awaiting input'}>
                <LazyBadge 
                  status="warning" 
                  text={<span className="text-xs text-amber-600 dark:text-amber-400">Needs Input</span>}
                  className="flex-shrink-0"
                />
              </LazyTooltip>
            ) : isStreaming ? (
              <LazyBadge status="processing" className="flex-shrink-0" />
            ) : conversation.status === 'active' ? (
              <LazyBadge status="success" className="flex-shrink-0" />
            ) : null}
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <p className="text-xs text-slate-400">{timeAgo}</p>
            {/* HITL type indicator */}
            {hasHITL && status?.pendingHITL?.type && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/40 text-amber-600 dark:text-amber-400">
                {status.pendingHITL.type === 'clarification' && '❓ Clarification'}
                {status.pendingHITL.type === 'decision' && '🤔 Decision'}
                {status.pendingHITL.type === 'env_var' && '🔑 Input needed'}
              </span>
            )}
          </div>
        </div>

        {/* Actions */}
        <LazyDropdown
          menu={{ items, onClick: handleMenuClick }}
          trigger={['click']}
          placement="bottomRight"
        >
          <LazyButton
            type="text"
            size="small"
            icon={<MoreVertical size={14} />}
            className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
            onClick={(e: React.MouseEvent) => e.stopPropagation()}
          />
        </LazyDropdown>
      </div>
    </button>
  );
});

ConversationItem.displayName = 'ConversationItem';

export const ConversationSidebar: FC<ConversationSidebarProps> = ({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
  onRename,
  collapsed,
  onToggleCollapse,
  headerExtra,
  conversationStatuses,
}) => {
  const [renamingConversation, setRenamingConversation] = useState<Conversation | null>(null);
  const [newTitle, setNewTitle] = useState('');
  const [isRenaming, setIsRenaming] = useState(false);
  // Use transition for non-urgent UI updates (rename operation)
  const [/* isPending */, startTransition] = useTransition();

  // Count conversations with pending HITL
  const pendingHITLCount = useMemo(() => {
    if (!conversationStatuses) return 0;
    let count = 0;
    conversationStatuses.forEach((status) => {
      if (status.pendingHITL) count++;
    });
    return count;
  }, [conversationStatuses]);

  const handleRenameClick = (conv: Conversation) => {
    setRenamingConversation(conv);
    setNewTitle(conv.title || '');
  };

  const handleRenameSubmit = async () => {
    if (!renamingConversation || !newTitle.trim()) return;

    setIsRenaming(true);
    try {
      await onRename?.(renamingConversation.id, newTitle.trim());
      // Use transition for non-urgent UI updates after successful rename
      startTransition(() => {
        setRenamingConversation(null);
        setNewTitle('');
      });
    } catch (error) {
      console.error('Failed to rename conversation:', error);
    } finally {
      setIsRenaming(false);
    }
  };

  const handleRenameCancel = () => {
    setRenamingConversation(null);
    setNewTitle('');
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className={`
        p-4 border-b border-slate-200 dark:border-slate-700
        ${collapsed ? 'flex items-center justify-center' : ''}
      `}>
        {collapsed ? (
          <div className="flex flex-col items-center gap-2">
            <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
              <Bot className="text-primary" size={24} />
            </div>
            {/* Collapse Toggle Button - Compact mode */}
            {onToggleCollapse && (
              <button
                type="button"
                onClick={onToggleCollapse}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                aria-label="展开侧边栏"
                title="展开侧边栏"
              >
                <PanelLeft size={18} />
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            {/* Title Row */}
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary to-primary-light flex items-center justify-center shadow-sm shrink-0">
                <Bot className="text-white" size={24} />
              </div>
              <div className="flex-1 min-w-0">
                <h2 className="font-semibold text-slate-900 dark:text-slate-100 truncate">Agent Chat</h2>
                <p className="text-xs text-slate-500">{conversations.length} conversations</p>
              </div>
              {/* Collapse Toggle Button */}
              {onToggleCollapse && (
                <button
                  type="button"
                  onClick={onToggleCollapse}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                  aria-label="收起侧边栏"
                  title="收起侧边栏"
                >
                  <PanelLeftClose size={18} />
                </button>
              )}
            </div>
            
            {/* Extra Header Content (e.g., Project Selector) */}
            {headerExtra && (
              <div className="flex items-center">
                {headerExtra}
              </div>
            )}
          </div>
        )}
      </div>

      {/* New Chat Button */}
      <div className={collapsed ? 'p-2' : 'p-4'}>
        <LazyButton
          type="primary"
          icon={<Plus size={18} />}
          onClick={onNew}
          className={`
            ${collapsed ? 'w-full aspect-square' : 'w-full'}
            h-10 bg-primary hover:bg-primary-600 shadow-sm
            rounded-xl flex items-center justify-center gap-2
          `}
        >
          {!collapsed && <span>New Chat</span>}
        </LazyButton>
      </div>

      {/* Pending HITL Alert Banner */}
      {!collapsed && pendingHITLCount > 0 && (
        <div className="mx-3 mb-2 p-2 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/50">
          <div className="flex items-center gap-2 text-amber-700 dark:text-amber-400">
            <AlertCircle size={14} />
            <span className="text-xs font-medium">
              {pendingHITLCount} conversation{pendingHITLCount > 1 ? 's' : ''} need{pendingHITLCount === 1 ? 's' : ''} your input
            </span>
          </div>
        </div>
      )}

      {/* Conversation List */}
      <div className={`
        flex-1 overflow-y-auto
        ${collapsed ? 'px-2' : 'px-3'}
      `}>
        <div className={collapsed ? '' : 'space-y-1'}>
          {conversations.map((conv) => (
            <ConversationItem
              key={conv.id}
              conversation={conv}
              isActive={conv.id === activeId}
              onSelect={() => onSelect(conv.id)}
              onDelete={(e) => onDelete(conv.id, e)}
              onRename={onRename ? () => handleRenameClick(conv) : undefined}
              compact={collapsed}
              status={conversationStatuses?.get(conv.id)}
            />
          ))}
        </div>
      </div>

      {/* Footer */}
      {!collapsed && (
        <div className="p-3 border-t border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-3 p-2 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 h-[52px]">
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary to-primary-light flex items-center justify-center shadow-sm">
              <Bot size={16} className="text-white" />
            </div>
            <div className="flex flex-col overflow-hidden min-w-0 flex-1">
              <p className="text-sm font-medium text-slate-900 dark:text-white truncate leading-5">
                AI Assistant
              </p>
              <p className="text-xs text-emerald-500 dark:text-emerald-400 truncate leading-4">
                Online
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Rename Modal */}
      <LazyModal
        title="Rename Conversation"
        open={!!renamingConversation}
        onOk={handleRenameSubmit}
        onCancel={handleRenameCancel}
        confirmLoading={isRenaming}
        okText="Rename"
        cancelText="Cancel"
      >
        <LazyInput
          placeholder="Enter conversation title"
          value={newTitle}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewTitle(e.target.value)}
          onPressEnter={handleRenameSubmit}
          autoFocus
        />
      </LazyModal>
    </div>
  );
};
