import React, { useState, useRef, useEffect } from 'react';

import type { WorkspaceMember, WorkspaceAgent } from '@/types/workspace';

export interface MentionInputProps {
  onSend: (content: string) => void;
  members: WorkspaceMember[];
  agents: WorkspaceAgent[];
  disabled?: boolean;
}

export const MentionInput: React.FC<MentionInputProps> = ({
  onSend,
  members,
  agents,
  disabled = false,
}) => {
  const [content, setContent] = useState('');
  const [showDropdown, setShowDropdown] = useState(false);
  const [filterText, setFilterText] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const allMentions = [
    ...members.map((m) => ({ id: m.id, type: 'human', name: m.user_email || m.user_id })),
    ...agents.map((a) => ({ id: a.id, type: 'agent', name: a.display_name || a.agent_id })),
  ];

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
        onSend(content.trim());
        setContent('');
      }
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    setContent(val);

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

  const selectMention = (mention: { name: string }) => {
    if (!textareaRef.current) return;
    
    const cursorPosition = textareaRef.current.selectionStart;
    const textBeforeCursor = content.slice(0, cursorPosition);
    const textAfterCursor = content.slice(cursorPosition);
    
    const mentionText = /^[\w][\w\-.]*$/.test(mention.name)
      ? `@${mention.name}`
      : `@"${mention.name}"`;
    const newTextBeforeCursor = textBeforeCursor.replace(/@[\w-]*$/, `${mentionText} `);
    
    setContent(newTextBeforeCursor + textAfterCursor);
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
    return () => { document.removeEventListener('mousedown', handleClickOutside); };
  }, []);

  return (
    <div className="relative w-full" ref={containerRef}>
      {showDropdown && filteredMentions.length > 0 && (
        <div 
          className="absolute z-10 w-64 max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-lg"
          style={{ bottom: '100%', left: 0, marginBottom: '8px' }}
        >
          {filteredMentions.map((mention, idx) => (
            <button
              type="button"
              key={`${mention.type}-${mention.id}`}
              className={`w-full px-4 py-2 cursor-pointer text-sm flex items-center justify-between border-0 ${
                idx === selectedIndex ? 'bg-blue-50 text-blue-600' : 'text-gray-700 hover:bg-gray-50 bg-white'
              }`}
              onClick={() => { selectMention(mention); }}
              onMouseEnter={() => { setSelectedIndex(idx); }}
            >
              <span>{mention.name}</span>
              <span className="text-xs text-gray-400 capitalize">{mention.type}</span>
            </button>
          ))}
        </div>
      )}
      
      <textarea
        ref={textareaRef}
        value={content}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder="Type a message... (Use @ to mention)"
        className="w-full min-h-[60px] max-h-32 p-3 text-sm bg-white border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none disabled:bg-gray-50 disabled:text-gray-500"
        rows={2}
      />
    </div>
  );
};
