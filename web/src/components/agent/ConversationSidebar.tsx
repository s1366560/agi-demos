/**
 * ConversationSidebar - Modern conversation list sidebar
 *
 * Features:
 * - Clean, modern design with glass morphism
 * - Status indicators with animations
 * - HITL pending indicators
 * - Streaming indicators
 * - Smooth hover effects
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
  PanelLeftClose,
  Sparkles,
} from 'lucide-react';

import {
  LazyButton,
  LazyBadge,
  LazyTooltip,
  LazyDropdown,
  LazyModal,
  LazyInput,
} from '@/components/ui/lazyAntd';

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

// Memoized ConversationItem
const ConversationItem = memo<ConversationItemProps>(
  ({ conversation, isActive, onSelect, onDelete, onRename, compact = false, status }) => {
    const timeAgo = useMemo(() => {
      try {
        return formatDistanceToNow(conversation.created_at);
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

    const items: MenuProps['items'] = useMemo(
      () => [
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
      ],
      [onDelete, onRename]
    );

    // Determine status indicator
    const hasHITL = status?.pendingHITL != null;
    const isStreaming = status?.isStreaming ?? false;

    if (compact) {
      return (
        <LazyTooltip
          title={
            <div>
              <div className="font-medium">{conversation.title || 'Untitled'}</div>
              {hasHITL && (
                <div className="text-amber-400 text-xs mt-1 flex items-center gap-1">
                  ⚠️ Needs input
                </div>
              )}
              {isStreaming && (
                <div className="text-blue-400 text-xs mt-1 flex items-center gap-1">
                  🔄 Processing
                </div>
              )}
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
            ${
              isActive
                ? 'bg-white dark:bg-slate-800 shadow-md border border-slate-200 dark:border-slate-700 text-primary'
                : 'text-slate-500 hover:bg-white/50 dark:hover:bg-slate-800/50'
            }
          `}
          >
            <MessageSquare size={20} />
            {isActive && <span className="absolute left-0 w-1 h-6 bg-primary rounded-r-full" />}
            {/* HITL indicator badge */}
            {hasHITL && (
              <span className="absolute -top-0.5 -right-0.5 w-3 h-3 bg-amber-500 rounded-full animate-pulse ring-2 ring-white dark:ring-slate-900" />
            )}
            {/* Streaming indicator */}
            {!hasHITL && isStreaming && (
              <span className="absolute -top-0.5 -right-0.5 w-3 h-3 bg-blue-500 rounded-full animate-pulse ring-2 ring-white dark:ring-slate-900" />
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
        transition-all duration-200
        ${
          isActive
            ? 'bg-white dark:bg-slate-800 shadow-md border border-slate-200 dark:border-slate-700'
            : 'hover:bg-white/60 dark:hover:bg-slate-800/40 border border-transparent'
        }
        ${hasHITL ? 'border-amber-200 dark:border-amber-800/50 bg-amber-50/30 dark:bg-amber-900/10' : ''}
      `}
      >
        <div className="flex items-start gap-3">
          {/* Icon with status indicator */}
          <div
            className={`
          relative w-10 h-10 rounded-xl flex items-center justify-center shrink-0
          transition-all duration-200
          ${
            hasHITL
              ? 'bg-gradient-to-br from-amber-100 to-orange-100 dark:from-amber-900/40 dark:to-orange-900/30 text-amber-600 dark:text-amber-400'
              : isActive
                ? 'bg-gradient-to-br from-primary/10 to-primary/5 text-primary'
                : 'bg-slate-100 dark:bg-slate-700/50 text-slate-500'
          }
        `}
          >
            {hasHITL ? (
              <AlertCircle size={18} className="animate-pulse" />
            ) : isStreaming ? (
              <Loader2 size={18} className="animate-spin" />
            ) : (
              <MessageSquare size={18} />
            )}

            {/* Status dot */}
            {(hasHITL || isStreaming) && (
              <span
                className={`
              absolute -top-0.5 -right-0.5 w-3 h-3 rounded-full ring-2 ring-white dark:ring-slate-900
              ${hasHITL ? 'bg-amber-500' : 'bg-blue-500'}
            `}
              />
            )}
          </div>

          {/* Content */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-2">
              <p
                className={`font-medium text-sm truncate ${isActive ? 'text-slate-900 dark:text-slate-100' : 'text-slate-700 dark:text-slate-300'}`}
              >
                {conversation.title || 'Untitled Conversation'}
              </p>
            </div>
            <div className="flex items-center gap-2 mt-1">
              <p className="text-xs text-slate-400">{timeAgo}</p>
              {/* Status badges */}
              {hasHITL ? (
                <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400 font-medium">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
                  Input needed
                </span>
              ) : isStreaming ? (
                <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400 font-medium">
                  <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
                  Processing
                </span>
              ) : conversation.status === 'active' ? (
                <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400 font-medium">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                  Active
                </span>
              ) : null}
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
              className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0 text-slate-400 hover:text-slate-600"
              onClick={(e: React.MouseEvent) => e.stopPropagation()}
            />
          </LazyDropdown>
        </div>
      </button>
    );
  }
);

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
  const [, /* isPending */ startTransition] = useTransition();

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
    <div className="h-full flex flex-col bg-slate-50/80 dark:bg-slate-900/50 backdrop-blur-sm">
      {/* Header */}
      <div
        className={`
        p-4 border-b border-slate-200/60 dark:border-slate-700/50
        ${collapsed ? 'flex items-center justify-center' : ''}
      `}
      >
        {collapsed ? (
          <div className="flex flex-col items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary to-primary-600 flex items-center justify-center shadow-lg shadow-primary/20">
              <Bot className="text-white" size={24} />
            </div>
            {/* Collapse Toggle Button - Compact mode */}
            {onToggleCollapse && (
              <button
                type="button"
                onClick={onToggleCollapse}
                className="p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-white dark:hover:bg-slate-800 transition-colors"
                aria-label="Expand sidebar"
                title="Expand sidebar"
              >
                <PanelLeft size={18} />
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            {/* Title Row */}
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary to-primary-600 flex items-center justify-center shadow-lg shadow-primary/20">
                <Bot className="text-white" size={24} />
              </div>
              <div className="flex-1 min-w-0">
                <h2 className="font-semibold text-slate-900 dark:text-slate-100 truncate text-base">
                  Agent Chat
                </h2>
                <p className="text-xs text-slate-500">
                  {conversations.length} conversation{conversations.length !== 1 ? 's' : ''}
                </p>
              </div>
              {/* Collapse Toggle Button */}
              {onToggleCollapse && (
                <button
                  type="button"
                  onClick={onToggleCollapse}
                  className="p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-white dark:hover:bg-slate-800 transition-colors"
                  aria-label="Collapse sidebar"
                  title="Collapse sidebar"
                >
                  <PanelLeftClose size={18} />
                </button>
              )}
            </div>

            {/* Extra Header Content (e.g., Project Selector) */}
            {headerExtra && <div className="flex items-center">{headerExtra}</div>}
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
            h-10 bg-gradient-to-r from-primary to-primary-600 hover:from-primary-600 hover:to-primary-700
            shadow-lg shadow-primary/20 hover:shadow-xl hover:shadow-primary/30
            rounded-xl flex items-center justify-center gap-2
            transition-all duration-200 hover:-translate-y-0.5
          `}
        >
          {!collapsed && <span className="font-medium">New Chat</span>}
        </LazyButton>
      </div>

      {/* Pending HITL Alert Banner */}
      {!collapsed && pendingHITLCount > 0 && (
        <div className="mx-4 mb-3 p-3 rounded-xl bg-gradient-to-r from-amber-50 to-orange-50 dark:from-amber-900/20 dark:to-orange-900/10 border border-amber-200 dark:border-amber-800/50">
          <div className="flex items-center gap-2 text-amber-700 dark:text-amber-400">
            <div className="w-8 h-8 rounded-lg bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center shrink-0">
              <AlertCircle size={16} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium">Input needed</p>
              <p className="text-xs text-amber-600 dark:text-amber-500">
                {pendingHITLCount} conversation{pendingHITLCount > 1 ? 's' : ''} awaiting response
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Conversation List */}
      <div
        className={`
        flex-1 overflow-y-auto custom-scrollbar
        ${collapsed ? 'px-2' : 'px-3'}
      `}
      >
        <div className={collapsed ? '' : 'space-y-1 py-2'}>
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

        {/* Empty state */}
        {!collapsed && conversations.length === 0 && (
          <div className="text-center py-12 px-4">
            <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
              <MessageSquare size={24} className="text-slate-400" />
            </div>
            <p className="text-sm text-slate-500 dark:text-slate-400 mb-1">No conversations yet</p>
            <p className="text-xs text-slate-400 dark:text-slate-500">Start a new chat to begin</p>
          </div>
        )}
      </div>

      {/* Footer */}
      {!collapsed && (
        <div className="p-4 border-t border-slate-200/60 dark:border-slate-700/50">
          <div className="flex items-center gap-3 p-3 rounded-xl bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-sm">
            <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-primary to-primary-600 flex items-center justify-center shadow-md shadow-primary/20">
              <Sparkles size={18} className="text-white" />
            </div>
            <div className="flex flex-col overflow-hidden min-w-0 flex-1">
              <p className="text-sm font-semibold text-slate-900 dark:text-white truncate">
                AI Assistant
              </p>
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                <p className="text-xs text-emerald-600 dark:text-emerald-400 font-medium">Online</p>
              </div>
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
        className="modern-modal"
      >
        <LazyInput
          placeholder="Enter conversation title"
          value={newTitle}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewTitle(e.target.value)}
          onPressEnter={handleRenameSubmit}
          autoFocus
          className="rounded-lg"
        />
      </LazyModal>
    </div>
  );
};

export default ConversationSidebar;
