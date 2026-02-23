/**
 * MessageActionBar - Hover-reveal action toolbar for messages
 *
 * Shows contextual actions (copy, retry, edit, delete) on message hover.
 * Supports both user and assistant message types.
 */

import React, { memo, useState, useCallback, useRef, useEffect } from 'react';

import { useTranslation } from 'react-i18next';

import {
  Copy,
  Check,
  RotateCcw,
  Pencil,
  Trash2,
  Bookmark,
  Pin,
  PinOff,
  Save,
  Reply,
  GitBranch,
} from 'lucide-react';

import { LazyTooltip } from '@/components/ui/lazyAntd';

export type MessageRole = 'user' | 'assistant';

export interface MessageAction {
  key: string;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
}

interface MessageActionBarProps {
  role: MessageRole;
  content: string;
  onRetry?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
  onBookmark?: () => void;
  onPin?: () => void;
  onSaveAsTemplate?: () => void;
  onReply?: () => void;
  onFork?: () => void;
  isPinned?: boolean;
  className?: string;
}

export const MessageActionBar: React.FC<MessageActionBarProps> = memo(
  ({
    role,
    content,
    onRetry,
    onEdit,
    onDelete,
    onBookmark,
    onPin,
    onSaveAsTemplate,
    onReply,
    onFork,
    isPinned,
    className = '',
  }) => {
    const { t } = useTranslation();
    const [copied, setCopied] = useState(false);
    const copyTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

    useEffect(() => {
      return () => {
        clearTimeout(copyTimerRef.current);
      };
    }, []);

    const handleCopy = useCallback(async () => {
      try {
        await navigator.clipboard.writeText(content);
        setCopied(true);
        clearTimeout(copyTimerRef.current);
        copyTimerRef.current = setTimeout(() => setCopied(false), 2000);
      } catch {
        // Fallback for older browsers
        const textArea = document.createElement('textarea');
        textArea.value = content;
        textArea.style.position = 'fixed';
        textArea.style.opacity = '0';
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
        setCopied(true);
        clearTimeout(copyTimerRef.current);
        copyTimerRef.current = setTimeout(() => setCopied(false), 2000);
      }
    }, [content]);

    const actions: MessageAction[] = [];

    // Copy - available for all messages
    // eslint-disable-next-line react-hooks/refs
    actions.push({
      key: 'copy',
      icon: copied ? <Check size={14} className="text-emerald-500" /> : <Copy size={14} />,
      label: copied ? t('agent.actions.copied', 'Copied!') : t('agent.actions.copy', 'Copy'),
      onClick: handleCopy,
    });

    // Reply - available for all messages
    if (onReply) {
      actions.push({
        key: 'reply',
        icon: <Reply size={14} />,
        label: t('agent.actions.reply', 'Reply'),
        onClick: onReply,
      });
    }

    // Fork - available for all messages
    if (onFork) {
      actions.push({
        key: 'fork',
        icon: <GitBranch size={14} />,
        label: t('agent.branch.fork', 'Fork from here'),
        onClick: onFork,
      });
    }

    if (role === 'assistant') {
      if (onRetry) {
        actions.push({
          key: 'retry',
          icon: <RotateCcw size={14} />,
          label: t('agent.actions.retry', 'Retry'),
          onClick: onRetry,
        });
      }
      if (onBookmark) {
        actions.push({
          key: 'bookmark',
          icon: <Bookmark size={14} />,
          label: t('agent.actions.bookmark', 'Bookmark'),
          onClick: onBookmark,
        });
      }
      if (onPin) {
        actions.push({
          key: 'pin',
          icon: isPinned ? <PinOff size={14} className="text-primary" /> : <Pin size={14} />,
          label: isPinned ? t('agent.actions.unpin', 'Unpin') : t('agent.actions.pin', 'Pin'),
          onClick: onPin,
        });
      }
      if (onSaveAsTemplate) {
        actions.push({
          key: 'saveTemplate',
          icon: <Save size={14} />,
          label: t('agent.templates.saveTitle', 'Save as Template'),
          onClick: onSaveAsTemplate,
        });
      }
    }

    if (role === 'user') {
      if (onEdit) {
        actions.push({
          key: 'edit',
          icon: <Pencil size={14} />,
          label: t('agent.actions.edit', 'Edit'),
          onClick: onEdit,
        });
      }
      if (onDelete) {
        actions.push({
          key: 'delete',
          icon: <Trash2 size={14} />,
          label: t('common.delete', 'Delete'),
          onClick: onDelete,
          danger: true,
        });
      }
    }

    if (actions.length === 0) return null;

    return (
      <div
        className={`
          flex items-center gap-0.5 px-1.5 py-1
          bg-white dark:bg-slate-800
          border border-slate-200 dark:border-slate-700
          rounded-lg shadow-sm
          opacity-0 group-hover:opacity-100 touch-show
          transition-opacity duration-200
          ${className}
        `}
      >
        {actions.map((action) => (
          <LazyTooltip key={action.key} title={action.label} placement="top">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                action.onClick();
              }}
              className={`
                p-1.5 rounded-md transition-colors duration-150
                ${
                  action.danger
                    ? 'text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20'
                    : 'text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700'
                }
              `}
              aria-label={action.label}
            >
              {action.icon}
            </button>
          </LazyTooltip>
        ))}
      </div>
    );
  }
);

MessageActionBar.displayName = 'MessageActionBar';

/**
 * CodeBlockCopyButton - Copy button for individual code blocks
 */
export const CodeBlockCopyButton: React.FC<{ code: string }> = memo(({ code }) => {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    return () => {
      clearTimeout(timerRef.current);
    };
  }, []);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      // silent fail
    }
  }, [code]);

  return (
    <LazyTooltip
      title={
        copied ? t('agent.actions.copied', 'Copied!') : t('agent.actions.copyCode', 'Copy code')
      }
      placement="top"
    >
      <button
        type="button"
        onClick={handleCopy}
        className="p-1 rounded hover:bg-slate-600 transition-colors text-slate-400 hover:text-slate-200"
        aria-label={t('agent.actions.copyCode', 'Copy code')}
      >
        {copied ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
      </button>
    </LazyTooltip>
  );
});

CodeBlockCopyButton.displayName = 'CodeBlockCopyButton';
