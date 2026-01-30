/**
 * ConversationSidebar - Modern conversation list sidebar
 */

import React, { useMemo } from 'react';
import { Button, Badge, Tooltip, Dropdown } from 'antd';
import type { MenuProps } from 'antd';
import { 
  Plus, 
  MessageSquare, 
  MoreVertical, 
  Trash2, 
  Edit3,
  Bot
} from 'lucide-react';
import type { Conversation } from '../../types/agent';
import { formatDistanceToNow } from '../../utils/date';

interface ConversationSidebarProps {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string, e: React.MouseEvent) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  headerExtra?: React.ReactNode;
}

interface ConversationItemProps {
  conversation: Conversation;
  isActive: boolean;
  onSelect: () => void;
  onDelete: (e: React.MouseEvent) => void;
  compact?: boolean;
}

const ConversationItem: React.FC<ConversationItemProps> = ({
  conversation,
  isActive,
  onSelect,
  onDelete,
  compact = false,
}) => {
  const timeAgo = useMemo(() => {
    try {
      return formatDistanceToNow(new Date(conversation.created_at));
    } catch {
      return '';
    }
  }, [conversation.created_at]);

  const items: MenuProps['items'] = [
    {
      key: 'rename',
      icon: <Edit3 size={14} />,
      label: 'Rename',
    },
    {
      key: 'delete',
      icon: <Trash2 size={14} />,
      label: 'Delete',
      danger: true,
    },
  ];

  const handleMenuClick: MenuProps['onClick'] = ({ key }) => {
    if (key === 'delete') {
      onDelete({} as React.MouseEvent);
    }
  };

  if (compact) {
    return (
      <Tooltip title={conversation.title || 'Untitled'} placement="right">
        <button
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
        </button>
      </Tooltip>
    );
  }

  return (
    <div
      onClick={onSelect}
      className={`
        group relative p-3 rounded-xl mb-1 cursor-pointer
        transition-all duration-200 border
        ${isActive 
          ? 'bg-slate-50 dark:bg-slate-800/60 border-slate-200 dark:border-slate-700 text-slate-900 dark:text-slate-100' 
          : 'bg-transparent border-transparent text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/40'
        }
      `}
    >
      <div className="flex items-start gap-3">
        {/* Icon */}
        <div className={`
          w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0
          ${isActive 
            ? 'bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300' 
            : 'bg-slate-100 dark:bg-slate-800 text-slate-500'
          }
        `}>
          <MessageSquare size={18} />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <p className="font-medium text-sm truncate">
              {conversation.title || 'Untitled Conversation'}
            </p>
            {conversation.status === 'active' && (
              <Badge status="processing" className="flex-shrink-0" />
            )}
          </div>
          <p className="text-xs text-slate-400 mt-0.5">{timeAgo}</p>
        </div>

        {/* Actions */}
        <Dropdown
          menu={{ items, onClick: handleMenuClick }}
          trigger={['click']}
          placement="bottomRight"
        >
          <Button
            type="text"
            size="small"
            icon={<MoreVertical size={14} />}
            className="opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
            onClick={(e) => e.stopPropagation()}
          />
        </Dropdown>
      </div>
    </div>
  );
};

export const ConversationSidebar: React.FC<ConversationSidebarProps> = ({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
  collapsed,
  headerExtra,
}) => {
  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className={`
        p-4 border-b border-slate-200 dark:border-slate-700
        ${collapsed ? 'flex items-center justify-center' : ''}
      `}>
        {collapsed ? (
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
            <Bot className="text-primary" size={24} />
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
        <Button
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
        </Button>
      </div>

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
              compact={collapsed}
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
    </div>
  );
};
