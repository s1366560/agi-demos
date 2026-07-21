import React, { useState, useRef, useEffect, useMemo, useId } from 'react';

import { useTranslation } from 'react-i18next';

import type { WorkspaceMember, WorkspaceAgent } from '@/types/workspace';

export interface MentionInputProps {
  /** Returns true when the message was accepted/sent; the draft is kept on failure. */
  onSend: (content: string, mentions: string[]) => boolean | Promise<boolean>;
  members: WorkspaceMember[];
  agents: WorkspaceAgent[];
  disabled?: boolean;
}

type MentionOption = {
  id: string;
  type: 'broadcast' | 'human' | 'agent';
  name: string;
};

type SelectedMention = MentionOption & {
  text: string;
};

export const MentionInput: React.FC<MentionInputProps> = ({
  onSend,
  members,
  agents,
  disabled = false,
}) => {
  const { t } = useTranslation();
  const [content, setContent] = useState('');
  const [showDropdown, setShowDropdown] = useState(false);
  const [filterText, setFilterText] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [selectedMentions, setSelectedMentions] = useState<SelectedMention[]>([]);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const listboxId = useId();

  const allMentions = useMemo<MentionOption[]>(
    () => [
      { id: 'all', type: 'broadcast', name: 'all' },
      ...members.map((m) => ({
        id: m.user_id,
        type: 'human' as const,
        name: m.user_email || m.user_id,
      })),
      ...agents.map((a) => ({
        id: a.agent_id,
        type: 'agent' as const,
        name: a.display_name || a.agent_id,
      })),
    ],
    [members, agents]
  );

  const mentionTypeLabels: Record<MentionOption['type'], string> = {
    broadcast: t('workspaceDetail.chat.mentionBroadcast', 'broadcast'),
    human: t('workspaceDetail.chat.mentionHuman', 'human'),
    agent: t('workspaceDetail.chat.mentionAgent', 'agent'),
  };

  const filteredMentions = allMentions.filter((m) =>
    m.name.toLowerCase().includes(filterText.toLowerCase())
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (showDropdown) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex((prev) => (prev + 1) % filteredMentions.length);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex((prev) => (prev - 1 + filteredMentions.length) % filteredMentions.length);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (filteredMentions.length > 0) {
          const mention = filteredMentions[selectedIndex];
          if (mention) selectMention(mention);
        }
      } else if (e.key === 'Escape') {
        e.preventDefault();
        setShowDropdown(false);
      }
      return;
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (content.trim()) {
        const result = onSend(
          content.trim(),
          selectedMentions.map((mention) => mention.id)
        );
        void Promise.resolve(result).then((sent) => {
          if (sent) {
            setContent('');
            setSelectedMentions([]);
          }
        });
      }
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    setContent(val);
    setSelectedMentions((prev) => prev.filter((mention) => val.includes(mention.text)));

    const cursorPosition = e.target.selectionStart;
    const textBeforeCursor = val.slice(0, cursorPosition);

    const match = textBeforeCursor.match(/@([\w-]*)$/);
    if (match && match[1] !== undefined) {
      setShowDropdown(true);
      setFilterText(match[1]);
      setSelectedIndex(0);
    } else {
      setShowDropdown(false);
    }
  };

  const selectMention = (mention: MentionOption) => {
    if (!textareaRef.current) return;

    const cursorPosition = textareaRef.current.selectionStart;
    const textBeforeCursor = content.slice(0, cursorPosition);
    const textAfterCursor = content.slice(cursorPosition);

    const mentionText = /^[\w][\w\-.]*$/.test(mention.name)
      ? `@${mention.name}`
      : `@"${mention.name}"`;
    const newTextBeforeCursor = textBeforeCursor.replace(/@[\w-]*$/, `${mentionText} `);

    setContent(newTextBeforeCursor + textAfterCursor);
    setSelectedMentions((prev) => [
      ...prev.filter((selected) => selected.id !== mention.id),
      { ...mention, text: mentionText },
    ]);
    setShowDropdown(false);

    setTimeout(() => {
      textareaRef.current?.focus();
      const newPos = newTextBeforeCursor.length;
      textareaRef.current?.setSelectionRange(newPos, newPos);
    }, 0);
  };

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  return (
    <div className="relative w-full" ref={containerRef}>
      {showDropdown && filteredMentions.length > 0 && (
        <div
          id={listboxId}
          role="listbox"
          aria-label={t('workspaceDetail.chat.mentionListAria', 'Mention suggestions')}
          className="absolute z-10 w-64 max-h-48 overflow-y-auto bg-white border border-slate-200 rounded-md shadow-lg dark:bg-slate-800 dark:border-slate-700"
          style={{ bottom: '100%', left: 0, marginBottom: '8px' }}
        >
          {filteredMentions.map((mention, idx) => (
            <button
              type="button"
              key={`${mention.type}-${mention.id}`}
              id={`${listboxId}-opt-${idx}`}
              role="option"
              aria-selected={idx === selectedIndex}
              tabIndex={-1}
              className={`w-full px-4 py-2 cursor-pointer text-sm flex items-center justify-between border-0 ${
                idx === selectedIndex
                  ? 'bg-blue-50 text-blue-600 dark:bg-blue-900/40 dark:text-blue-300'
                  : 'text-slate-700 hover:bg-slate-50 bg-white dark:text-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700'
              }`}
              onClick={() => {
                selectMention(mention);
              }}
              onMouseEnter={() => {
                setSelectedIndex(idx);
              }}
            >
              <span>{mention.name}</span>
              <span className="text-xs text-slate-400 capitalize dark:text-slate-500">
                {mentionTypeLabels[mention.type]}
              </span>
            </button>
          ))}
        </div>
      )}

      <textarea
        ref={textareaRef}
        aria-label={t('workspaceDetail.chat.messageInputAria', 'Chat message input')}
        role="combobox"
        aria-expanded={showDropdown && filteredMentions.length > 0}
        aria-controls={listboxId}
        aria-autocomplete="list"
        aria-activedescendant={
          showDropdown && filteredMentions.length > 0
            ? `${listboxId}-opt-${selectedIndex}`
            : undefined
        }
        value={content}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder={t(
          'workspaceDetail.chat.messagePlaceholder',
          'Type a message… (Use @ to mention)'
        )}
        className="w-full min-h-[60px] max-h-32 p-3 text-sm bg-white border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none disabled:bg-slate-50 disabled:text-slate-500 dark:bg-slate-800 dark:border-slate-600 dark:text-slate-100 dark:disabled:bg-slate-800 dark:disabled:text-slate-500"
        rows={2}
      />
    </div>
  );
};
