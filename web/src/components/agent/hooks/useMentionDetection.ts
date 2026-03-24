import { useState, useCallback, useRef } from 'react';

import type { MentionItem } from '@/services/mentionService';

import type { MentionPopoverHandle } from '../chat/MentionPopover';

interface UseMentionDetectionParams {
  content: string;
  setContent: React.Dispatch<React.SetStateAction<string>>;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
}

interface UseMentionDetectionReturn {
  mentionVisible: boolean;
  mentionQuery: string;
  mentionSelectedIndex: number;
  setMentionSelectedIndex: React.Dispatch<React.SetStateAction<number>>;
  handleMentionSelect: (item: MentionItem) => void;
  /** Process textarea value + cursor for @-mention detection. */
  processMentionInput: (value: string, cursorPos: number) => void;
  /** Handle keyboard events when mention dropdown is visible. Returns true if consumed. */
  handleMentionKeyDown: (e: React.KeyboardEvent) => boolean;
  setMentionVisible: React.Dispatch<React.SetStateAction<boolean>>;
  setMentionQuery: React.Dispatch<React.SetStateAction<string>>;
  mentionPopoverRef: React.RefObject<MentionPopoverHandle | null>;
  selectedSubAgent: string | null;
  setSelectedSubAgent: React.Dispatch<React.SetStateAction<string | null>>;
  handleRemoveSubAgent: () => void;
  resetMention: () => void;
}

export function useMentionDetection({
  content,
  setContent,
  textareaRef,
}: UseMentionDetectionParams): UseMentionDetectionReturn {
  const [mentionVisible, setMentionVisible] = useState(false);
  const [mentionQuery, setMentionQuery] = useState('');
  const [mentionSelectedIndex, setMentionSelectedIndex] = useState(0);
  const [selectedSubAgent, setSelectedSubAgent] = useState<string | null>(null);

  const mentionPopoverRef = useRef<MentionPopoverHandle>(null);

  const handleMentionSelect = useCallback(
    (item: MentionItem) => {
      const textarea = textareaRef.current;
      if (!textarea) return;

      const cursorPos = textarea.selectionStart;
      const textBefore = content.slice(0, cursorPos);
      const textAfter = content.slice(cursorPos);

      const atIndex = textBefore.lastIndexOf('@');
      if (atIndex === -1) return;

      if (item.type === 'subagent') {
        setSelectedSubAgent(item.name);
        setMentionVisible(false);
        setMentionQuery('');

        const before = content.slice(0, atIndex);
        const newContent = before + textAfter;
        setContent(newContent);

        setTimeout(() => {
          textarea.focus();
          textarea.setSelectionRange(atIndex, atIndex);
        }, 50);
        return;
      }

      const before = content.slice(0, atIndex);
      const replacement = `@${item.name} `;
      const newContent = before + replacement + textAfter;

      setContent(newContent);
      setMentionVisible(false);
      setMentionQuery('');

      const newCursor = atIndex + replacement.length;
      setTimeout(() => {
        textarea.focus();
        textarea.setSelectionRange(newCursor, newCursor);
      }, 0);
    },
    [content, setContent, textareaRef]
  );

  const handleRemoveSubAgent = useCallback(() => {
    setSelectedSubAgent(null);
  }, []);

  const processMentionInput = useCallback(
    (value: string, cursorPos: number) => {
      const textBefore = value.slice(0, cursorPos);
      const mentionMatch = textBefore.match(/@([^\s@]*)$/);
      if (mentionMatch) {
        setMentionQuery(mentionMatch[1] ?? '');
        setMentionVisible(true);
        setMentionSelectedIndex(0);
      } else if (mentionVisible) {
        setMentionVisible(false);
        setMentionQuery('');
      }
    },
    [mentionVisible]
  );

  const handleMentionKeyDown = useCallback(
    (e: React.KeyboardEvent): boolean => {
      if (!mentionVisible) return false;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setMentionSelectedIndex((prev) => prev + 1);
        return true;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setMentionSelectedIndex((prev) => Math.max(0, prev - 1));
        return true;
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        const item = mentionPopoverRef.current?.getSelectedItem();
        if (item) {
          handleMentionSelect(item);
        }
        return true;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        setMentionVisible(false);
        setMentionQuery('');
        return true;
      }
      return false;
    },
    [mentionVisible, handleMentionSelect]
  );

  const resetMention = useCallback(() => {
    setMentionVisible(false);
    setMentionQuery('');
    setSelectedSubAgent(null);
  }, []);

  return {
    mentionVisible,
    mentionQuery,
    mentionSelectedIndex,
    setMentionSelectedIndex,
    handleMentionSelect,
    processMentionInput,
    handleMentionKeyDown,
    setMentionVisible,
    setMentionQuery,
    mentionPopoverRef,
    selectedSubAgent,
    setSelectedSubAgent,
    handleRemoveSubAgent,
    resetMention,
  };
}
