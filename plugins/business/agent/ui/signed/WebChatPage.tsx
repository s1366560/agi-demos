import { SlashCommandDropdown } from '../../../../../web/src/components/agent/SlashCommandDropdown';
import { useSlashCommand } from '../../../../../web/src/components/agent/hooks/useSlashCommand';
import { SelectedSkillChip } from '../web/chat/SelectedSkillChip';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { App, ConfigProvider, Dropdown, theme } from 'antd';
import enUS from 'antd/es/locale/en_US';
import zhCN from 'antd/es/locale/zh_CN';
import { lightTheme, darkTheme } from '../../../../../web/src/theme/antdTheme';
import { ChevronDown, Clock3, Download, GitCompareArrows, ListChecks } from 'lucide-react';
import i18n from 'i18next';
import { I18nextProvider, useTranslation } from 'react-i18next';
import { MemoryRouter } from 'react-router-dom';
import type { RichPageContext } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import { EmptyState } from '../../../../../web/src/components/agent/EmptyState';
import { SplitPaneLayout } from '../../../../../web/src/components/agent/SplitPaneLayout';
import { ChatSearch } from '../../../../../web/src/components/agent/chat/ChatSearch';
import { OnboardingTour } from '../../../../../web/src/components/agent/chat/OnboardingTour';
import { invoke } from './reviewAuthority';
import { ShortcutOverlay } from '../../../../../web/src/components/agent/chat/ShortcutOverlay';
import { ExecutionTargetBadge } from '../../../../../web/src/components/execution-target/ExecutionTargetBadge';
import { ChatExecutionPlacement } from './ChatExecutionPlacement';
import { DesktopRunContext } from './DesktopRunContext';
import { useLayoutModeStore, type LayoutMode } from '../../../../../web/src/stores/layoutMode';
import type { TimelineEvent } from '../../../../../web/src/types/agent';
import { AgentChatColumn, AgentStatusFrame } from '../web/chat/AgentChatColumn';
import { AgentComposerCard, AgentDraftSurface } from '../web/chat/AgentComposerCard';
import { ChatDraftInput } from '../web/chat/ChatDraftInput';
import { ChatLayoutSelector } from '../web/chat/ChatLayoutSelector';
import { formatDateTime } from '../../../../../sdk/memstack-plugin-sdk/ui/localDate';
import { EmptyConversation } from '../web/chat/EmptyConversation';
import { ICON_BUTTON_CLASSES, LAYOUT_BG_CLASSES } from '../web/chat/styles';
import { ConversationCompareView } from '../../../../../web/src/components/agent/comparison/ConversationCompareView';
import { ConversationPickerModal } from '../../../../../web/src/components/agent/comparison/ConversationPickerModal';
import type { Conversation } from '../../../../../web/src/types/agent';
import { conversationTimeline, exportConversation } from './exportConversation';
import english from '../web/locales/en-US.json';
import chinese from '../web/locales/zh-CN.json';
import { Transcript } from './ChatTranscriptView';
import { InteractionPanel } from './InteractionPanel';
import { SelectedRunReview, type RunProjection } from './SelectedRunReview';
import { WebChatStatus } from './WebChatStatus';
import { usePageDarkMode } from './chatContextAuthority';
import { WebActivity } from './WebActivity';
import { LinkedPackagePanel, openSnippet, SignedCanvas, SignedTaskList } from './WebChatPanels';
import { useCanvasBlocks } from './useCanvasBlocks';
import { WebComposerControls } from './WebComposerControls';
import { useChat } from './useChat';
import { useInteractions } from './useInteractions';
import { latestPosition, timelineCount, transcriptRows } from './transcriptRows';
import { foldTurns, foldableTurns } from './foldTurns';
import { useConversationTasks } from './useConversationTasks';
import { runningSandboxTool, useProjectSandbox } from './sandboxStatus';
import { useTurnCollapse } from '../web/transcript/message/useTurnCollapse';
import { PinnedMessages } from '../web/transcript/message/PinnedMessages';
import { chatTranscriptItems } from './WebChatTranscript';
import './webChat.css';

/**
 * The title of the conversation in the header. It takes the width of its text,
 * as a plain title does, and is renamed in place.
 */
function ConversationTitle({
  title,
  label,
  disabled,
  onRename,
}: {
  title: string;
  label: string;
  disabled: boolean;
  onRename: (value: string) => void;
}) {
  const [draft, setDraft] = useState(title);
  return (
    <div className="relative min-w-0">
      <span
        aria-hidden="true"
        className="block invisible truncate text-sm font-medium text-slate-800 dark:text-slate-100"
      >
        {draft}
      </span>
      <input
        className="absolute inset-0 w-full truncate bg-transparent text-sm font-medium text-slate-800 outline-none dark:text-slate-100"
        aria-label={label}
        title={title}
        value={draft}
        disabled={disabled}
        onChange={(event) => setDraft(event.currentTarget.value)}
        onBlur={(event) => {
          const value = event.currentTarget.value.trim();
          if (value && value !== title) onRename(value);
          else setDraft(title);
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter') event.currentTarget.blur();
        }}
      />
    </div>
  );
}

function WebChatPage({ scope }: { scope: RichPageContext }) {
  const { t } = useTranslation();
  const toast = App.useApp().message;
  // Reasoning that streams in follows the events the page has read so far.
  const read = useRef<[number, number] | undefined>(undefined);
  const chat = useChat(scope, () => read.current);
  const slash = useSlashCommand({ onSend: (text) => void chat.send(text), onInputClear: () => chat.setDraft('') });
  const sendDraft = () => void chat.send(chat.draft, slash.selectedSkill?.name);
  const resetSlash = slash.resetSlash;
  useEffect(() => {
    if (chat.run) resetSlash();
  }, [chat.run, resetSlash]);
  const [focused, setFocused] = useState(false);
  const [plan, setPlan] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [tour, setTour] = useState(false);
  const [tourFailure, setTourFailure] = useState('');
  useEffect(() => {
    if (!scope.commands.includes('chat-welcome')) return;
    const controller = new AbortController();
    void invoke<{ complete: boolean }>('chat-welcome', {}, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) setTour(!value.complete);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setTourFailure(String(error));
      });
    return () => controller.abort();
  }, [scope]);
  // The layout is the one of the original workbench, and it is kept from one load
  // to the next, as it is there.
  const mode = useLayoutModeStore((s) => s.mode);
  const ratio = useLayoutModeStore((s) => s.splitRatio);
  const setMode = useLayoutModeStore((s) => s.setMode);
  const setSplitRatio = useLayoutModeStore((s) => s.setSplitRatio);
  const [search, setSearch] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());
  // A code block of the transcript opens as a document of the canvas, as in the
  // original workbench.
  const openCode = useCallback((content: string, language?: string) => {
    openSnippet(content, language);
    setMode('canvas');
  }, [setMode]);
  const refill = (value: string) => {
    chat.setDraft(value);
    input.current?.focus();
  };
  const interactionsEnabled =
    chat.selectedRow?.execution_target === 'cloud' &&
    scope.commands.includes('chat-interactions');
  const interactions = useInteractions(chat.selected, !!chat.run, interactionsEnabled, chat.page);
  // Canvas blocks of the conversation open as tabs of the canvas.
  useCanvasBlocks(chat.selected, interactions.events);
  useEffect(() => {
    read.current = latestPosition(interactions.events);
  }, [interactions.events]);
  const rows = useMemo(
    () => transcriptRows(chat.messages, chat.thoughts, interactions.events),
    [chat.messages, chat.thoughts, interactions.events]
  );
  // The task list is read once, for the status bar and for the task pane.
  const tasks = useConversationTasks(
    chat.selected,
    !!chat.run,
    scope.commands.includes('chat-project-context')
  );
  // The sandbox of the project, and the sandbox tool that is running, for the status bar.
  const sandbox = useProjectSandbox(scope, chat.writing);
  // As in the original status bar, a sandbox tool is named while a turn runs, and
  // not for a call of the history that was refused and never returned.
  const tool = useMemo(
    () => (chat.run ? runningSandboxTool(interactions.events) : undefined),
    [chat.run, interactions.events]
  );
  // Rows of the timeline the way the original workbench counts them.
  const count = useMemo(
    () =>
      timelineCount(
        chat.messages,
        chat.thoughts,
        interactions.ready ? interactions.events : []
      ),
    [chat.messages, chat.thoughts, interactions.ready, interactions.events]
  );
  // A turn can be folded to one line, and an answer can be pinned above the
  // messages, as in the original transcript.
  const turnCollapse = useTurnCollapse(chat.selected);
  const [pinned, setPinned] = useState<Set<string>>(() => new Set());
  const shown = useMemo(
    () => rows.filter((row) => row.kind !== 'message' || !hidden.has(row.id)),
    [rows, hidden]
  );
  const entries = useMemo(
    () => foldTurns(shown, turnCollapse.collapsed),
    [shown, turnCollapse.collapsed]
  );
  const foldable = useMemo(() => foldableTurns(shown), [shown]);
  const pinnedMessages = useMemo(
    () =>
      [...pinned]
        .map((id) => ({ id, content: chat.messages.find((row) => row.id === id)?.content ?? '' }))
        .filter((row) => row.content),
    [pinned, chat.messages]
  );
  // An answer can be kept as a prompt template of the project, as in the original workbench.
  const saveTemplate = scope.commands.includes('chat-save-template')
    ? async (content: string, title: string, category: string) => {
        await invoke('chat-save-template', { title, content, category });
      }
    : undefined;
  const togglePin = (id: string) =>
    setPinned((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  // A conversation opened while its turn is running is followed from what was read.
  const followed = useRef(-1);
  const { selected, loading, run, page, ownPage } = chat;
  const { messages, thoughts } = chat;
  const { ready, events } = interactions;
  useEffect(() => {
    if (!selected || !ready || loading || run || page === ownPage || followed.current === page)
      return;
    followed.current = page;
    const from = latestPosition([...messages, ...thoughts, ...events]);
    if (from) void chat.follow(selected, from);
  }, [selected, ready, loading, run, page, ownPage, messages, thoughts, events]);
  // Earlier history is read together with the tool steps of the same page.
  const loadOlder = () => {
    const before = chat.cursor;
    if (!before || !chat.selected || chat.loading || chat.busy) return;
    void interactions.older(before).catch(chat.report);
    void chat.older();
  };
  const workspace = chat.selectedRow?.workspace_id ?? new URLSearchParams(scope.search).get('workspaceId');
  const executionTarget = chat.selectedRow?.execution_target ?? chat.target;
  const readOnly = executionTarget === 'local' && !chat.hasDevice;
  const placeholder = t('agent.inputBar.placeholder', "Ask me anything, or type '/' for commands…");
  const disabled = readOnly || (!!chat.selected && chat.loading);
  const timeline = useMemo(
    () =>
      chat.messages.filter(message => !hidden.has(message.id)).map(
        (message, index) =>
          ({
            ...message,
            type: message.role,
            role: message.role === 'user_message' ? 'user' : 'assistant',
            eventTimeUs: message.eventTimeUs ?? (message.timestamp ?? 0) * 1000,
            timestamp: message.timestamp ?? (message.eventTimeUs ?? 0) / 1000,
            eventCounter: index,
          }) as TimelineEvent
      ),
    [chat.messages, hidden]
  );

  useEffect(() => {
    function shortcuts(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'f') {
        event.preventDefault();
        setSearch((value) => !value);
      }
      if (
        event.key === '/' &&
        !event.ctrlKey &&
        !event.metaKey &&
        !(event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement)
      ) {
        event.preventDefault();
        input.current?.focus();
      }
    }
    window.addEventListener('keydown', shortcuts);
    return () => window.removeEventListener('keydown', shortcuts);
  }, []);
  useEffect(() => {
    setHidden(new Set());
    setPinned(new Set());
  }, [chat.selected]);
  // The original workbench keeps the division of a layout only for the session.
  const setLayout = (next: LayoutMode) => setMode(next);
  // The conversation beside another one, and the conversation as a file, as in the
  // original status bar.
  const [compare, setCompare] = useState(false);
  const [compareWith, setCompareWith] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);
  const exportable = chat.messages.length > 0;
  const comparable = !!chat.selected && exportable;
  const doExport = (format: 'markdown' | 'pdf') =>
    exportConversation(
      conversationTimeline(chat, interactions.events),
      format,
      chat.selectedRow?.title ?? t('agent.sidebar.conversations', 'Conversation'),
      `conversation-${chat.selected}.${format === 'pdf' ? 'pdf' : 'md'}`
    ).catch((error: unknown) =>
      toast.error(error instanceof Error ? error.message : String(error))
    );
  const conversations = chat.list as unknown as Conversation[];
  const header = (
    <>
      <WebActivity scope={scope} onOpen={chat.choose} />
      <SelectedRunReview
        {...(chat.local ? { renderContext: (run: RunProjection) => <DesktopRunContext run={run} /> } : {})}
        enabled={scope.commands.includes('review-latest')}
        conversation={chat.selected}
        busy={chat.busy}
      />
    </>
  );
  const identity = chat.selectedRow && (
    <>
      <ExecutionTargetBadge
        executionTarget={chat.selectedRow.execution_target}
        running={!!chat.run}
      />
      <div className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
        <ConversationTitle
          key={`${chat.selected}:${chat.selectedRow.title}`}
          title={chat.selectedRow.title}
          disabled={chat.busy || !scope.commands.includes('chat-rename')}
          label={chat.label('Conversation title', '会话标题')}
          onRename={(value) => void chat.rename(value)}
        />
        {chat.selectedRow.created_at && (
          <span
            className="hidden shrink-0 items-center gap-1 text-xs text-slate-500 dark:text-slate-400 sm:inline-flex"
            title={formatDateTime(chat.selectedRow.created_at)}
          >
            <Clock3 size={12} />
            {t('agent.chat.header.createdAt', {
              date: formatDateTime(chat.selectedRow.created_at),
              defaultValue: 'Created {{date}}',
            })}
          </span>
        )}
      </div>
    </>
  );
  const history = (
    <>
      {!chat.selected ? (
        <EmptyState
          projectId={
            scope.commands.includes('chat-project-context')
              ? (scope.projectId ?? undefined)
              : undefined
          }
          lastConversation={chat.list[0]}
          onResumeConversation={chat.choose}
          onNewConversation={chat.create}
          onSendPrompt={chat.send}
        />
      ) : (
        <Transcript
          chat={chat}
          older={loadOlder}
          settled={interactions.ready}
          welcome={null}
          above={(jump) => (
            <PinnedMessages
              pinned={pinnedMessages}
              onJump={jump}
              onUnpin={togglePin}
            />
          )}
          items={chatTranscriptItems({
            entries,
            chat,
            scope,
            streaming: !!chat.run,
            refill,
            openCode,
            hide: (id) => setHidden((current) => new Set([...current, id])),
            pinned,
            onPin: togglePin,
            foldFor: (row) => {
              const hiddenCount = foldable.get(row.id);
              return hiddenCount
                ? {
                    folded: turnCollapse.isCollapsed(row.id),
                    hiddenCount,
                    onToggle: () => turnCollapse.toggle(row.id),
                  }
                : undefined;
            },
            onExpand: turnCollapse.toggle,
            ...(saveTemplate ? { saveTemplate } : {}),
          })}
        >
          <InteractionPanel
            conversation={chat.selected}
            enabled={interactionsEnabled}
            interactions={interactions}
            tools={false}
            active={!!chat.run}
            desktop={false}
            emptyActivity={!chat.loading && !chat.messages.length ? <EmptyConversation /> : null}
            // As in the original transcript, canvas content is shown in the canvas
            // pane and not inside the messages.
            section="activity"
          />
        </Transcript>
      )}
      <ChatSearch timeline={timeline} visible={search} onClose={() => setSearch(false)} />
    </>
  );
  const composer = (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col p-2 sm:p-4">
      {chat.error && (
        <div role="alert" className="text-xs text-red-700">
          {chat.error}
        </div>
      )}
      <AgentComposerCard
        isFocused={focused}
        isPlanMode={plan}
        isDragging={dragging}
        disabled={disabled}
        onDragOver={(event) => {
          if (executionTarget === 'cloud' && !disabled && event.dataTransfer.types.includes('Files')) {
            event.preventDefault();
            setDragging(true);
          }
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          setDragging(false);
          if (event.dataTransfer.files.length) {
            event.preventDefault();
            if (executionTarget === 'cloud' && !disabled && scope.commands.includes('chat-upload'))
              void chat.attachFiles(Array.from(event.dataTransfer.files));
          }
        }}
      >
        {plan && (
          <div className="flex-shrink-0 px-3 pt-2 sm:px-4">
            <div
              data-testid="plan-mode-strip"
              className="flex items-center gap-2 rounded-md border border-primary/25 bg-primary/5 px-2.5 py-1.5"
            >
              <ListChecks size={12} />
              <span className="text-xs font-semibold text-primary">
                {t('agent.inputBar.planModeLabel', 'Plan Mode')}
              </span>
              <span className="hidden min-w-0 flex-1 truncate text-xs text-primary/70 sm:inline">
                {t(
                  'agent.inputBar.planModeHint',
                  'Read-only analysis. Agent will plan without making changes.'
                )}
              </span>
            </div>
          </div>
        )}
        <AgentDraftSurface controls={<SlashCommandDropdown ref={slash.slashDropdownRef} visible={slash.slashDropdownVisible} query={slash.slashQuery}
              onSelect={slash.handleSlashSelect} onClose={()=>slash.setSlashDropdownVisible(false)} selectedIndex={slash.slashSelectedIndex}
              onSelectedIndexChange={slash.setSlashSelectedIndex}/>}>
          {slash.selectedSkill && <SelectedSkillChip name={slash.selectedSkill.name} remove={slash.handleRemoveSkill}/>}
          <ChatDraftInput
            ref={input}
            disabled={disabled}
            aria-label={placeholder}
            placeholder={placeholder}
            value={chat.draft}
            onChange={(event) => {
              const field = event.currentTarget;
              field.style.height = 'auto';
              field.style.height =
                Math.max(
                  32,
                  Math.min(field.scrollHeight, field.parentElement?.clientHeight || 400)
                ) + 'px';
              chat.setDraft(field.value);
              if (scope.commands.includes('chat-project-context')) slash.processSlashInput(field.value);
            }}
            onPaste={(event) => {
              if (
                !disabled && executionTarget === 'cloud' &&
                event.clipboardData.files.length &&
                scope.commands.includes('chat-upload')
              ) {
                event.preventDefault();
                void chat.attachFiles(Array.from(event.clipboardData.files));
              }
            }}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            onKeyDown={(event) => {
              if (!event.nativeEvent.isComposing && slash.handleSlashKeyDown(event)) return;
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                if (!disabled && !chat.run) sendDraft();
              }
            }}
          />
        </AgentDraftSurface>
        <WebComposerControls scope={scope} chat={chat} onPlanModeChange={setPlan} onSubmit={sendDraft} onSlashSelect={slash.handleSlashSelect} />
      </AgentComposerCard>
    </div>
  );
  const column = (
    <AgentChatColumn
      header={header}
      identity={identity}
      timeline={history}
      composer={composer}
      placement={<ChatExecutionPlacement chat={chat} />}
    />
  );
  const status = (
    <AgentStatusFrame
      status={
        <WebChatStatus
          scope={scope}
          conversation={chat.selected}
          count={count}
          tasks={tasks.tasks}
          sandbox={sandbox}
          tool={tool}
          running={chat.writing}
        />
      }
      actions={
        <>
          {comparable && (
            <button
              type="button"
              onClick={() => {
                setCompare(true);
                setPicking(true);
              }}
              className={ICON_BUTTON_CLASSES}
              title={t('comparison.compare', 'Compare')}
              aria-label={t('comparison.compare', 'Compare')}
            >
              <GitCompareArrows size={14} />
            </button>
          )}
          {exportable && (
            <Dropdown
              menu={{
                items: [
                  { key: 'markdown', label: t('agent.actions.exportMarkdown', 'Export as Markdown') },
                  // A workbench without a printer does not offer a PDF.
                  ...(window.memstack.printPdf
                    ? [{ key: 'pdf', label: t('agent.actions.exportPdf', 'Export as PDF') }]
                    : []),
                ],
                onClick: ({ key }) => void doExport(key === 'pdf' ? 'pdf' : 'markdown'),
              }}
              trigger={['click']}
            >
              <button
                type="button"
                className={`${ICON_BUTTON_CLASSES} gap-0.5`}
                title={t('agent.actions.export', 'Export')}
                aria-label={t('agent.actions.export', 'Export')}
              >
                <Download size={14} />
                <ChevronDown size={10} />
              </button>
            </Dropdown>
          )}
          <ChatLayoutSelector mode={mode} setMode={setLayout} hasWorkspace={!!workspace} />
        </>
      }
    />
  );
  // The comparison stands in place of the conversation, as in the original workbench.
  if (compare && chat.selected)
    return (
      <div className={'flex h-full w-full flex-col overflow-hidden ' + LAYOUT_BG_CLASSES}>
        <ConversationCompareView
          projectId={scope.projectId ?? ''}
          leftConversationId={chat.selected}
          rightConversationId={compareWith}
          conversations={conversations}
          onClose={() => {
            setCompare(false);
            setCompareWith(null);
          }}
          onSelectRight={() => setPicking(true)}
        />
        <ConversationPickerModal
          visible={picking}
          currentConversationId={chat.selected}
          conversations={conversations}
          onSelect={setCompareWith}
          onClose={() => setPicking(false)}
        />
      </div>
    );
  return (
    <div className={'flex h-full w-full flex-col overflow-hidden ' + LAYOUT_BG_CLASSES}>
      <ShortcutOverlay />
      {tour && !chat.selected && (
        <OnboardingTour
          onComplete={() => {
            setTour(false);
            void invoke('chat-welcome', { complete: true }).catch((error) =>
              setTourFailure(String(error))
            );
          }}
        />
      )}
      {tourFailure && <div role="alert">{tourFailure}</div>}
      <main
        className="flex-1 flex flex-col min-w-0 h-full overflow-hidden relative"
        aria-label={t('agent.focusDesktop.chat', 'Chat')}
      >
        {mode === 'chat' ? (
          <>
            {column}
            {status}
          </>
        ) : (
          <SplitPaneLayout
            leftContent={column}
            splitRatio={ratio}
            onSplitRatioChange={setSplitRatio}
            statusBar={status}
            handleAccentColor={
              mode === 'canvas' ? 'violet' : mode === 'task' ? 'purple' : 'primary'
            }
            rightContent={
              mode === 'task' ? (
                <SignedTaskList tasks={tasks.tasks} failure={tasks.failure} />
              ) : mode === 'canvas' ? (
                <SignedCanvas
                  scope={scope}
                  chat={chat}
                  interactions={interactions}
                  back={() => setMode('chat')}
                />
              ) : (
                <LinkedPackagePanel mode={mode} workspace={workspace} report={chat.report} />
              )
            }
          />
        )}
      </main>
    </div>
  );
}

async function mount() {
  const scope = await window.memstack.getContext();
  document.documentElement.dataset.pageTarget = scope.target;
  const lng = scope.locale.startsWith('zh') ? 'zh' : 'en';
  // Date helpers of the shared transcript read the default instance, so the page
  // initializes that one instead of a private instance.
  await i18n.init({
    lng,
    resources: { [lng]: { translation: lng === 'zh' ? chinese : english } },
    interpolation: { escapeValue: false },
  });
  createRoot(document.getElementById('root')!).render(
    <I18nextProvider i18n={i18n}>
      <PageTheme scope={scope} />
    </I18nextProvider>
  );
}
function PageTheme({ scope: loaded }: { scope: RichPageContext }) {
  const dark = usePageDarkMode();
  // A page that keeps itself mounted learns the address it moved to.
  const [scope, setScope] = useState(loaded);
  useEffect(
    () => window.memstack.onContextChange?.((next) => setScope(next)),
    []
  );
  return (
    <ConfigProvider
      locale={scope.locale.startsWith('zh') ? zhCN : enUS}
      theme={dark ? { ...darkTheme, algorithm: theme.darkAlgorithm } : lightTheme}
    >
      <App className="contents">
        <MemoryRouter initialEntries={[scope.pathname]}>
          <WebChatPage scope={scope} />
        </MemoryRouter>
      </App>
    </ConfigProvider>
  );
}
void mount();
