/**
 * CanvasPanel - Side-by-side artifact editing panel
 *
 * Displays a tabbed editor/viewer for code, markdown, and preview content.
 * Inspired by ChatGPT Canvas and Claude Artifacts.
 *
 * Features:
 * - Multiple tabs for open artifacts
 * - Code syntax highlighting (lazy-loaded)
 * - Markdown preview
 * - Copy/Download toolbar per tab
 * - Empty state with guidance
 */

import { memo, useState, useCallback, useRef, useMemo } from 'react';

import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';

import {
  X,
  Copy,
  Download,
  FileCode2,
  FileText,
  Eye,
  Table,
  Check,
  PanelLeftClose,
  Pencil,
  Sparkles,
  Undo2,
  Redo2,
} from 'lucide-react';
import remarkGfm from 'remark-gfm';

import {
  useCanvasStore,
  useActiveCanvasTab,
  useCanvasActions,
  type CanvasTab,
  type CanvasContentType,
} from '@/stores/canvasStore';
import { useLayoutModeStore } from '@/stores/layoutMode';

import { SelectionToolbar } from './SelectionToolbar';

const typeIcon = (type: CanvasContentType, size = 14) => {
  switch (type) {
    case 'code':
      return <FileCode2 size={size} />;
    case 'markdown':
      return <FileText size={size} />;
    case 'preview':
      return <Eye size={size} />;
    case 'data':
      return <Table size={size} />;
  }
};

// Tab bar
const CanvasTabBar = memo(() => {
  const tabs = useCanvasStore((s) => s.tabs);
  const activeTabId = useCanvasStore((s) => s.activeTabId);
  const { setActiveTab, closeTab } = useCanvasActions();
  const { t } = useTranslation();
  const setMode = useLayoutModeStore((s) => s.setMode);

  if (tabs.length === 0) return null;

  return (
    <div className="flex items-center border-b border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-900/50">
      <div className="flex-1 flex items-center overflow-x-auto scrollbar-none">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`
              group flex items-center gap-1.5 px-3 py-2 text-xs font-medium
              border-r border-slate-200/60 dark:border-slate-700/60
              transition-colors whitespace-nowrap max-w-[180px]
              ${
                tab.id === activeTabId
                  ? 'bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200'
                  : 'text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800/50'
              }
            `}
          >
            <span className={tab.id === activeTabId ? 'text-primary' : 'text-slate-400'}>
              {typeIcon(tab.type)}
            </span>
            <span className="truncate">{tab.title}</span>
            {tab.dirty && (
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 flex-shrink-0" />
            )}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                closeTab(tab.id);
              }}
              className="ml-1 p-0.5 rounded opacity-0 group-hover:opacity-100 hover:bg-slate-200 dark:hover:bg-slate-700 transition-all"
            >
              <X size={12} />
            </button>
          </button>
        ))}
      </div>
      <button
        type="button"
        onClick={() => setMode('chat')}
        className="flex-shrink-0 p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
        title={t('agent.canvas.backToChat', 'Back to chat')}
      >
        <PanelLeftClose size={16} />
      </button>
    </div>
  );
});
CanvasTabBar.displayName = 'CanvasTabBar';

// Content area for a single tab
const CanvasContent = memo<{
  tab: CanvasTab;
  editMode: boolean;
  onContentChange: (content: string) => void;
}>(({ tab, editMode, onContentChange }) => {
  if (editMode && (tab.type === 'code' || tab.type === 'markdown' || tab.type === 'data')) {
    const bgClass =
      tab.type === 'code'
        ? 'bg-slate-900 text-slate-200'
        : 'bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200';
    return (
      <div className={`h-full overflow-auto ${tab.type === 'code' ? 'bg-slate-900' : ''}`}>
        <textarea
          value={tab.content}
          onChange={(e) => onContentChange(e.target.value)}
          className={`w-full h-full font-mono text-sm p-4 resize-none focus:outline-none ${bgClass}`}
          spellCheck={false}
        />
      </div>
    );
  }

  switch (tab.type) {
    case 'code':
      return (
        <div className="h-full overflow-auto bg-slate-900">
          <pre className="p-4 text-sm font-mono text-slate-200 whitespace-pre-wrap break-words leading-relaxed">
            <code>{tab.content}</code>
          </pre>
        </div>
      );
    case 'markdown':
      return (
        <div className="h-full overflow-auto p-6">
          <div className="prose prose-sm dark:prose-invert max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{tab.content}</ReactMarkdown>
          </div>
        </div>
      );
    case 'preview':
      return (
        <iframe
          srcDoc={tab.content}
          sandbox="allow-scripts"
          className="w-full h-full border-0 bg-white"
          title={tab.title}
        />
      );
    case 'data':
      return (
        <div className="h-full overflow-auto p-4">
          <pre className="text-sm font-mono text-slate-700 dark:text-slate-300 whitespace-pre-wrap">
            {tab.content}
          </pre>
        </div>
      );
  }
});
CanvasContent.displayName = 'CanvasContent';

// Toolbar for copy/download actions
const CanvasToolbar = memo<{
  tab: CanvasTab;
  editMode: boolean;
  onToggleEdit: () => void;
}>(({ tab, editMode, onToggleEdit }) => {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const { undo, redo, canUndo, canRedo } = useCanvasActions();

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(tab.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback
      const textarea = document.createElement('textarea');
      textarea.value = tab.content;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [tab.content]);

  const handleDownload = useCallback(() => {
    const ext = tab.type === 'code' ? (tab.language || 'txt') : tab.type === 'markdown' ? 'md' : 'txt';
    const blob = new Blob([tab.content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${tab.title}.${ext}`;
    a.click();
    URL.revokeObjectURL(url);
  }, [tab]);

  const canEdit = tab.type !== 'preview';

  return (
    <div className="flex items-center gap-1 px-3 py-1.5 border-b border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800">
      <div className="flex-1 flex items-center gap-2">
        <span className="text-primary">{typeIcon(tab.type)}</span>
        <span className="text-xs font-medium text-slate-600 dark:text-slate-300">{tab.title}</span>
        {tab.language && (
          <span className="text-[10px] px-1.5 py-0.5 bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400 rounded">
            {tab.language}
          </span>
        )}
      </div>
      <button
        type="button"
        onClick={() => undo(tab.id)}
        disabled={!canUndo(tab.id)}
        className="p-1.5 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
        title={t('agent.canvas.undo', 'Undo (Ctrl+Z)')}
      >
        <Undo2 size={14} />
      </button>
      <button
        type="button"
        onClick={() => redo(tab.id)}
        disabled={!canRedo(tab.id)}
        className="p-1.5 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
        title={t('agent.canvas.redo', 'Redo (Ctrl+Shift+Z)')}
      >
        <Redo2 size={14} />
      </button>
      {canEdit && (
        <button
          type="button"
          onClick={onToggleEdit}
          className={`p-1.5 rounded-md transition-colors ${
            editMode
              ? 'bg-primary/10 text-primary'
              : 'hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-400'
          }`}
          title={editMode ? t('agent.canvas.viewMode', 'View mode') : t('agent.canvas.editMode', 'Edit mode')}
        >
          {editMode ? <Eye size={14} /> : <Pencil size={14} />}
        </button>
      )}
      <button
        type="button"
        onClick={handleCopy}
        className="p-1.5 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
        title={t('agent.canvas.copy', 'Copy')}
      >
        {copied ? <Check size={14} className="text-emerald-500" /> : <Copy size={14} />}
      </button>
      <button
        type="button"
        onClick={handleDownload}
        className="p-1.5 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
        title={t('agent.canvas.download', 'Download')}
      >
        <Download size={14} />
      </button>
    </div>
  );
});
CanvasToolbar.displayName = 'CanvasToolbar';

// Quick actions toolbar based on content type
const QuickActions = memo<{
  type: CanvasContentType;
  content: string;
  onSendPrompt?: (prompt: string) => void;
}>(({ type, content, onSendPrompt }) => {
  const { t } = useTranslation();

  const actions = useMemo(() => {
    const common = [
      {
        label: t('agent.canvas.actions.summarize', 'Summarize'),
        prompt: `Summarize this:\n\n${content.slice(0, 500)}`,
      },
    ];

    if (type === 'code') {
      return [
        {
          label: t('agent.canvas.actions.explain', 'Explain'),
          prompt: `Explain this code:\n\n${content.slice(0, 500)}`,
        },
        {
          label: t('agent.canvas.actions.optimize', 'Optimize'),
          prompt: `Optimize this code:\n\n${content.slice(0, 500)}`,
        },
        {
          label: t('agent.canvas.actions.addTests', 'Add Tests'),
          prompt: `Write tests for this code:\n\n${content.slice(0, 500)}`,
        },
        {
          label: t('agent.canvas.actions.addComments', 'Add Comments'),
          prompt: `Add comments to this code:\n\n${content.slice(0, 500)}`,
        },
      ];
    }
    if (type === 'markdown') {
      return [
        {
          label: t('agent.canvas.actions.improve', 'Improve'),
          prompt: `Improve this text:\n\n${content.slice(0, 500)}`,
        },
        {
          label: t('agent.canvas.actions.shorten', 'Shorten'),
          prompt: `Make this more concise:\n\n${content.slice(0, 500)}`,
        },
        {
          label: t('agent.canvas.actions.translate', 'Translate'),
          prompt: `Translate this to the other language (if Chinese, translate to English; if English, translate to Chinese):\n\n${content.slice(0, 500)}`,
        },
        ...common,
      ];
    }
    return common;
  }, [type, content, t]);

  if (!onSendPrompt || !content) return null;

  return (
    <div className="flex items-center gap-1 px-3 py-1.5 border-b border-slate-200 dark:border-slate-700 overflow-x-auto scrollbar-none">
      {actions.map((action) => (
        <button
          key={action.label}
          type="button"
          onClick={() => onSendPrompt(action.prompt)}
          className="px-2 py-1 text-xs rounded-md bg-slate-50 dark:bg-slate-700/50 text-slate-600 dark:text-slate-300 hover:bg-primary/10 hover:text-primary transition-colors whitespace-nowrap"
        >
          {action.label}
        </button>
      ))}
    </div>
  );
});
QuickActions.displayName = 'QuickActions';

// Empty state when no tabs
const CanvasEmptyState = memo(() => {
  const { t } = useTranslation();

  return (
    <div className="h-full flex flex-col items-center justify-center p-8 text-center">
      <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-violet-100 to-purple-100 dark:from-violet-900/30 dark:to-purple-900/20 flex items-center justify-center mb-4">
        <FileCode2 size={28} className="text-violet-500 dark:text-violet-400" />
      </div>
      <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-200 mb-2">
        {t('agent.canvas.emptyTitle', 'Canvas')}
      </h3>
      <p className="text-sm text-slate-500 dark:text-slate-400 max-w-xs leading-relaxed">
        {t(
          'agent.canvas.emptyDescription',
          'Code, documents, and previews from the agent will appear here. Ask the agent to generate or edit content.'
        )}
      </p>
    </div>
  );
});
CanvasEmptyState.displayName = 'CanvasEmptyState';

// Main CanvasPanel component
export const CanvasPanel = memo<{ onSendPrompt?: (prompt: string) => void }>(
  ({ onSendPrompt }) => {
    const activeTab = useActiveCanvasTab();
    const { updateContent } = useCanvasActions();
    const contentRef = useRef<HTMLDivElement>(null);
    const [editMode, setEditMode] = useState(false);
    const { t } = useTranslation();

    const handleSelectionAction = useCallback(
      (prompt: string) => {
        onSendPrompt?.(prompt);
      },
      [onSendPrompt]
    );

    const handleContentChange = useCallback(
      (content: string) => {
        if (activeTab) {
          updateContent(activeTab.id, content);
        }
      },
      [activeTab, updateContent]
    );

    const handleToggleEdit = useCallback(() => {
      setEditMode((prev) => !prev);
    }, []);

    const handleAskRefine = useCallback(() => {
      if (onSendPrompt && activeTab) {
        onSendPrompt(
          `I've edited the content below. Please review and improve it:\n\n${activeTab.content}`
        );
        setEditMode(false);
      }
    }, [onSendPrompt, activeTab]);

    return (
      <div className="h-full flex flex-col bg-white dark:bg-slate-900 overflow-hidden">
        <CanvasTabBar />
        {activeTab ? (
          <>
            <CanvasToolbar
              tab={activeTab}
              editMode={editMode}
              onToggleEdit={handleToggleEdit}
            />
            <QuickActions
              type={activeTab.type}
              content={activeTab.content}
              onSendPrompt={onSendPrompt}
            />
            <div ref={contentRef} className="flex-1 min-h-0 overflow-hidden relative">
              <CanvasContent
                tab={activeTab}
                editMode={editMode}
                onContentChange={handleContentChange}
              />
              {!editMode && (
                <SelectionToolbar containerRef={contentRef} onAction={handleSelectionAction} />
              )}
              {editMode && onSendPrompt && (
                <button
                  type="button"
                  onClick={handleAskRefine}
                  className="absolute bottom-4 right-4 px-3 py-1.5 bg-primary text-white text-xs rounded-lg shadow-lg hover:bg-primary-600 flex items-center gap-1.5"
                >
                  <Sparkles size={12} />
                  {t('agent.canvas.askRefine', 'Ask Agent to Refine')}
                </button>
              )}
            </div>
          </>
        ) : (
          <CanvasEmptyState />
        )}
      </div>
    );
  }
);
CanvasPanel.displayName = 'CanvasPanel';
