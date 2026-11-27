import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, Download, Pin, PinOff, Plus, Redo2, Sparkles, Undo2, X } from 'lucide-react';
import { TaskList } from '../../../../../web/src/components/agent/TaskList';
import type { AgentTask } from '../../../../../web/src/types/agent';
import { useCanvasStore } from '../../../../../web/src/stores/canvasStore';
import type { RichPageContext } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import {
  CanvasWelcome,
  type EditableCanvasType,
} from '../web/canvas/CanvasWelcome';
import { A2UISurfaceRenderer } from '../web/canvas/A2UISurfaceRenderer';
import { Answer } from './ChatTranscriptView';
import { SignedFileExplorer } from './SignedFileExplorer';
import type { Interactions } from './useInteractions';
import type { Chat } from './useChat';

/** The task pane. The page reads the list once, for this pane and for the status bar. */
export function SignedTaskList({
  tasks,
  failure,
}: {
  tasks: AgentTask[];
  failure: string;
}) {
  return failure ? <div role="alert">{failure}</div> : <TaskList tasks={tasks} />;
}

// What the agent is asked to do with a document of the canvas, or with what is
// selected in it. Each one sends a turn of the conversation.
const OPERATIONS = [
  'explain',
  'optimize',
  'addTests',
  'addComments',
  'improve',
  'shorten',
  'translate',
  'summarize',
] as const;
type Operation = (typeof OPERATIONS)[number];

/** Open a code block of the transcript as a document; the same text opens the same one. */
export function openSnippet(content: string, language?: string) {
  let hash = 0;
  for (const char of content) hash = (hash * 31 + char.charCodeAt(0)) | 0;
  const canvas = useCanvasStore.getState();
  canvas.openTab({
    id: `snippet-${hash}`,
    title: language ? `snippet.${language}` : 'snippet.txt',
    type: 'code',
    content,
    language,
  });
  return canvas;
}

/**
 * The canvas of the original workbench: what the agent produced and what the user
 * opened are tabs, one of which is shown at a time, kept from one load to the
 * next. The agent can be asked to work on a document, or on a selection in it.
 */
export function SignedCanvas({
  chat,
  scope,
  interactions,
  back,
}: {
  chat: Chat;
  scope: RichPageContext;
  interactions: Interactions;
  /** Leave the canvas for the conversation. */
  back: () => void;
}) {
  const { t } = useTranslation();
  const tabs = useCanvasStore((s) => s.tabs);
  const activeTabId = useCanvasStore((s) => s.activeTabId);
  const setActiveTab = useCanvasStore((s) => s.setActiveTab);
  const closeTab = useCanvasStore((s) => s.closeTab);
  const togglePin = useCanvasStore((s) => s.togglePin);
  const updateContent = useCanvasStore((s) => s.updateContent);
  const undo = useCanvasStore((s) => s.undo);
  const redo = useCanvasStore((s) => s.redo);
  const active = tabs.find((tab) => tab.id === activeTabId) ?? null;
  // What the store keeps of the edits of a document, as its undo and redo read it.
  const canUndo = (active?.historyIndex ?? -1) >= 0;
  const canRedo = active ? active.historyIndex + 2 < active.history.length : false;
  const [editing, setEditing] = useState(false);
  const [selection, setSelection] = useState('');
  const activeId = active?.id;
  useEffect(() => {
    setEditing(false);
    setSelection('');
  }, [activeId]);
  const text = active?.type === 'a2ui-surface' ? '' : (active?.content ?? '');
  const surface = active?.type === 'a2ui-surface';
  const markdown = active?.type === 'markdown';
  const picture = active?.type === 'preview' && /^data:image\//.test(text);
  const editor = !surface && !picture && (!markdown || editing);
  const canAsk =
    scope.commands.includes('chat-turn') && !chat.run && !chat.loading && !chat.busy;
  // A request goes to the conversation, where its answer is written.
  const ask = (prompt: string) => {
    setSelection('');
    void chat.send(prompt);
    back();
  };
  const operate = (operation: Operation) => {
    const chosen = selection || text;
    if (!canAsk || !chosen.trim()) return;
    const fenced = '```' + (active?.language ?? '') + '\n' + chosen + '\n```';
    ask(t(`agent.canvas.actionPrompts.${operation}`, { content: fenced }));
  };
  const refine = () => {
    if (!canAsk || !text.trim()) return;
    ask(t('agent.canvas.askRefinePrompt', { content: text }));
  };
  const request = active
    ? interactions.requests.find(
        (r) => r.request_type === 'a2ui_action' && r.block_id === active.id
      )
    : undefined;
  const selected = (field: HTMLTextAreaElement) =>
    setSelection(field.value.slice(field.selectionStart, field.selectionEnd));
  // A document is handed to the user as a file; the workbench offers it under the name of its tab.
  const download = async () => {
    if (!active || surface || picture || !window.memstack.saveFile) return;
    const markdown = active.type === 'markdown';
    await window.memstack.saveFile(
      /\.[A-Za-z0-9]{1,8}$/.test(active.title) ? active.title : `${active.title}.${markdown ? 'md' : 'txt'}`,
      { text: active.content },
      markdown ? 'text/markdown;charset=utf-8' : 'text/plain;charset=utf-8'
    );
  };
  const headerButton = (name: string, onPress: () => void, icon: ReactNode, disabled = false) => (
    <button
      type="button"
      onClick={onPress}
      disabled={disabled}
      title={name}
      aria-label={name}
      className="flex h-7 w-7 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:cursor-not-allowed disabled:opacity-50 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
    >
      {icon}
    </button>
  );
  return (
    <div className="flex h-full min-h-0 w-full">
      <SignedFileExplorer scope={scope} conversation={chat.selected} />
    <div className="flex h-full min-w-0 flex-1 flex-col bg-white dark:bg-slate-950">
      <div
        role="tablist"
        aria-label={t('agent.canvas.emptyTitle')}
        className="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-slate-200 px-2 py-1 dark:border-slate-800"
      >
        <button
          type="button"
          onClick={back}
          title={t('agent.canvas.backToChat')}
          aria-label={t('agent.canvas.backToChat')}
          className="shrink-0 rounded p-1 text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
        >
          <ArrowLeft size={14} />
        </button>
        {tabs.map((tab) => (
          <div
            key={tab.id}
            role="tab"
            aria-selected={tab.id === active?.id}
            onClick={() => setActiveTab(tab.id)}
            className={`group flex max-w-[180px] shrink-0 cursor-pointer items-center gap-1 rounded px-2 py-1 text-xs ${
              tab.id === active?.id
                ? 'bg-slate-100 font-medium text-slate-800 dark:bg-slate-800 dark:text-slate-100'
                : 'text-slate-500 hover:bg-slate-50 dark:text-slate-400 dark:hover:bg-slate-900'
            }`}
          >
            {tab.pinned && <Pin size={11} className="shrink-0 text-primary" />}
            <span className="truncate" title={tab.title}>
              {tab.title}
            </span>
            <button
              type="button"
              aria-label={t(tab.pinned ? 'agent.canvas.unpinTab' : 'agent.canvas.pinTab', {
                title: tab.title,
              })}
              onClick={(event) => {
                event.stopPropagation();
                togglePin(tab.id);
              }}
              className="rounded p-0.5 opacity-0 hover:bg-slate-200 focus:opacity-100 group-hover:opacity-100 dark:hover:bg-slate-700"
            >
              {tab.pinned ? <PinOff size={11} /> : <Pin size={11} />}
            </button>
            <button
              type="button"
              aria-label={t('agent.canvas.closeTab', { title: tab.title })}
              onClick={(event) => {
                event.stopPropagation();
                closeTab(tab.id, true);
              }}
              className="rounded p-0.5 opacity-0 hover:bg-slate-200 focus:opacity-100 group-hover:opacity-100 dark:hover:bg-slate-700"
            >
              <X size={11} />
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() => openDocument('code', t('agent.canvas.newCode'))}
          title={t('agent.canvas.newTab')}
          aria-label={t('agent.canvas.newTab')}
          className="shrink-0 rounded p-1 text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
        >
          <Plus size={14} />
        </button>
      </div>
      {active && (
        <div className="flex h-9 shrink-0 items-center gap-1 border-b border-slate-100 px-2 dark:border-slate-800">
          <span className="min-w-0 flex-1 truncate text-xs font-medium text-slate-700 dark:text-slate-200" title={active.title}>
            {active.title}
          </span>
          {editor && active && (
            <>
              {headerButton(t('agent.canvas.undo'), () => undo(active.id), <Undo2 size={14} />, !canUndo)}
              {headerButton(t('agent.canvas.redo'), () => redo(active.id), <Redo2 size={14} />, !canRedo)}
            </>
          )}
          {!surface && !picture &&
            headerButton(t('agent.canvas.download'), () => void download(), <Download size={14} />)}
        </div>
      )}
      {active && (
        <div
          role="toolbar"
          aria-label={t('agent.canvas.emptyTitle')}
          className="flex shrink-0 flex-wrap items-center gap-1 border-b border-slate-100 px-2 py-1 dark:border-slate-800"
        >
          <Sparkles size={12} className="ml-1 shrink-0 text-primary" />
          {OPERATIONS.map((operation) => (
            <button
              key={operation}
              type="button"
              disabled={!canAsk || !(selection || text).trim()}
              onClick={() => operate(operation)}
              title={selection ? t('agent.canvas.selectionAsk') : undefined}
              className="rounded px-1.5 py-0.5 text-2xs font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              {t(`agent.canvas.actions.${operation}`)}
            </button>
          ))}
          <button
            type="button"
            disabled={!canAsk || !text.trim()}
            onClick={refine}
            className="rounded px-1.5 py-0.5 text-2xs font-medium text-primary hover:bg-primary/5 disabled:opacity-50"
          >
            {t('agent.canvas.askRefine')}
          </button>
          {markdown && (
            <button
              type="button"
              onClick={() => setEditing((value) => !value)}
              className="ml-auto rounded px-1.5 py-0.5 text-2xs font-medium text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              {t(editing ? 'agent.canvas.viewMode' : 'agent.canvas.editMode')}
            </button>
          )}
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto">
        {!active ? (
          <CanvasWelcome
            handleNew={(type, title) => openDocument(type as EditableCanvasType, title)}
          />
        ) : surface ? (
          <A2UISurfaceRenderer
            surfaceId={active.a2uiSurfaceId ?? active.id}
            messages={active.a2uiMessages ?? active.content}
            useAuthority={() => ({
              conversationId: chat.selected,
              hitlRequestId: request?.id,
              respondToA2UIAction: async (_id, name, source, context) => {
                if (!request) throw new Error('request_not_pending');
                await interactions.respond(request, {
                  action_name: name,
                  source_component_id: source,
                  context,
                });
              },
            })}
          />
        ) : picture ? (
          <img src={text} alt={active.title} className="max-w-full object-contain p-4" />
        ) : editor ? (
          <textarea
            value={text}
            onChange={(event) => active && updateContent(active.id, event.target.value)}
            onSelect={(event) => selected(event.currentTarget)}
            onKeyUp={(event) => selected(event.currentTarget)}
            onMouseUp={(event) => selected(event.currentTarget)}
            className="h-full w-full resize-none bg-slate-900 p-4 font-mono text-sm text-slate-200 focus:outline-none"
            spellCheck={false}
            aria-label={t('agent.canvas.editorLabel', {
              title: active.title,
              defaultValue: 'Editor for {{title}}',
            })}
          />
        ) : (
          <div className="p-4">
            <Answer text={text} />
          </div>
        )}
      </div>
    </div>
    </div>
  );
}

function openDocument(type: EditableCanvasType, title: string) {
  useCanvasStore.getState().openTab({ id: crypto.randomUUID(), title, type, content: '' });
}

export function LinkedPackagePanel({
  mode,
  workspace,
  report,
}: {
  mode: 'code' | 'collab';
  workspace: string | null;
  report: (error: unknown) => void;
}) {
  const { t } = useTranslation();
  const anchor = useRef<HTMLDivElement>(null);
  const callback = useRef(report);
  callback.current = report;
  useEffect(() => {
    if (!anchor.current) return;
    if (!window.memstack.anchorSlot) {
      callback.current('page_host_upgrade_required');
      return;
    }
    const search =
      mode === 'collab' && workspace ? '?' + new URLSearchParams({ workspaceId: workspace }) : '';
    return window.memstack.anchorSlot(mode + '@1', anchor.current, search, (reason) =>
      callback.current(reason)
    );
  }, [mode, workspace]);
  return (
    <div
      ref={anchor}
      className="h-full min-h-0 w-full"
      aria-label={
        mode === 'code'
          ? t('agent.layout.modes.code', 'Code')
          : t('agent.layout.modes.collab', 'Collab')
      }
    />
  );
}
