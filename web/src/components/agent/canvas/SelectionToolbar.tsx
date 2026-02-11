/**
 * SelectionToolbar - Floating toolbar that appears on text selection in CanvasPanel
 *
 * Shows action buttons (Explain, Simplify, Expand) that send the selected text
 * as a follow-up prompt to the agent chat.
 */

import { useState, useEffect, useCallback, memo } from 'react';

import { useTranslation } from 'react-i18next';

import { MessageSquare, Minimize2, Maximize2, HelpCircle } from 'lucide-react';

interface SelectionToolbarProps {
  containerRef: React.RefObject<HTMLElement | null>;
  onAction: (action: string, selectedText: string) => void;
}

interface Position {
  top: number;
  left: number;
}

export const SelectionToolbar = memo<SelectionToolbarProps>(({ containerRef, onAction }) => {
  const { t } = useTranslation();
  const [visible, setVisible] = useState(false);
  const [position, setPosition] = useState<Position>({ top: 0, left: 0 });
  const [selectedText, setSelectedText] = useState('');

  const handleSelectionChange = useCallback(() => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount) {
      setVisible(false);
      return;
    }

    const text = selection.toString().trim();
    if (text.length < 3) {
      setVisible(false);
      return;
    }

    const container = containerRef.current;
    if (!container) {
      setVisible(false);
      return;
    }

    const range = selection.getRangeAt(0);
    const ancestor = range.commonAncestorContainer;
    if (!container.contains(ancestor)) {
      setVisible(false);
      return;
    }

    const rect = range.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();

    setSelectedText(text);
    setPosition({
      top: rect.top - containerRect.top - 44,
      left: Math.max(0, rect.left - containerRect.left + rect.width / 2 - 100),
    });
    setVisible(true);
  }, [containerRef]);

  useEffect(() => {
    document.addEventListener('selectionchange', handleSelectionChange);
    return () => document.removeEventListener('selectionchange', handleSelectionChange);
  }, [handleSelectionChange]);

  useEffect(() => {
    const handleMouseDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target.closest('[data-selection-toolbar]')) {
        setTimeout(() => setVisible(false), 150);
      }
    };
    document.addEventListener('mousedown', handleMouseDown);
    return () => document.removeEventListener('mousedown', handleMouseDown);
  }, []);

  if (!visible) return null;

  const actions = [
    {
      key: 'explain',
      icon: <HelpCircle size={13} />,
      label: t('agent.canvas.selectionExplain', 'Explain'),
      prompt: (text: string) => `Explain the following:\n\n${text}`,
    },
    {
      key: 'simplify',
      icon: <Minimize2 size={13} />,
      label: t('agent.canvas.selectionSimplify', 'Simplify'),
      prompt: (text: string) => `Simplify the following:\n\n${text}`,
    },
    {
      key: 'expand',
      icon: <Maximize2 size={13} />,
      label: t('agent.canvas.selectionExpand', 'Expand'),
      prompt: (text: string) => `Expand on the following with more detail:\n\n${text}`,
    },
    {
      key: 'ask',
      icon: <MessageSquare size={13} />,
      label: t('agent.canvas.selectionAsk', 'Ask about'),
      prompt: (text: string) => `Regarding this: "${text}"\n\n`,
    },
  ];

  return (
    <div
      data-selection-toolbar
      className="absolute z-50 flex items-center gap-0.5 px-1 py-1 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-xl"
      style={{ top: position.top, left: position.left }}
    >
      {actions.map((action) => (
        <button
          key={action.key}
          type="button"
          onClick={() => onAction(action.prompt(selectedText), selectedText)}
          className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-md transition-colors whitespace-nowrap"
          title={action.label}
        >
          {action.icon}
          <span>{action.label}</span>
        </button>
      ))}
    </div>
  );
});
SelectionToolbar.displayName = 'SelectionToolbar';
