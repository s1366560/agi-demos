import { SlashCommandDropdown } from '../../../../../web/src/components/agent/SlashCommandDropdown';
import { useSlashCommand } from '../../../../../web/src/components/agent/hooks/useSlashCommand';
import { SelectedSkillChip } from '../web/chat/SelectedSkillChip';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { App, ConfigProvider, theme } from 'antd';
import enUS from 'antd/locale/en_US';
import zhCN from 'antd/locale/zh_CN';
import { lightTheme, darkTheme } from '../../../../../web/src/theme/antdTheme';
import { Clock3, ListChecks } from 'lucide-react';
import { createInstance } from 'i18next';
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
import type { LayoutMode } from '../../../../../web/src/stores/layoutMode';
import type { TimelineEvent } from '../../../../../web/src/types/agent';
import { AgentChatColumn, AgentStatusFrame } from '../web/chat/AgentChatColumn';
import { AgentComposerCard, AgentDraftSurface } from '../web/chat/AgentComposerCard';
import { ChatDraftInput } from '../web/chat/ChatDraftInput';
import { ChatLayoutSelector } from '../web/chat/ChatLayoutSelector';
import { formatDateTime } from '../../../../../sdk/memstack-plugin-sdk/ui/localDate';
import { EmptyConversation } from '../web/chat/EmptyConversation';
import { LAYOUT_BG_CLASSES } from '../web/chat/styles';
import english from '../web/locales/en-US.json';
import chinese from '../web/locales/zh-CN.json';
import { Transcript } from './ChatTranscriptView';
import { InteractionPanel } from './InteractionPanel';
import { SelectedRunReview } from './SelectedRunReview';
import { WebChatStatus } from './WebChatStatus';
import { usePageDarkMode } from './chatContextAuthority';
import { WebActivity } from './WebActivity';
import {
  LinkedPackagePanel,
  SignedCanvas,
  SignedTaskList,
  type CanvasDraft,
} from './WebChatPanels';
import { WebComposerControls } from './WebComposerControls';
import { useChat } from './useChat';
import './webChat.css';

import { WebChatMessage } from './WebChatMessage';

function WebChatPage({ scope }: { scope: RichPageContext }) {
  const { t } = useTranslation();
  const chat = useChat(scope);
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
  const [mode, setMode] = useState<LayoutMode>('chat');
  const [ratio, setRatio] = useState(0.5);
  const [search, setSearch] = useState(false);
  const [draftCanvas, setDraftCanvas] = useState<CanvasDraft | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());
  const openCode = useCallback((content: string, language?: string) => {
    setDraftCanvas({ type: 'code', title: language ? 'snippet.' + language : 'snippet.txt', content });
    setMode('canvas');
    setRatio(0.35);
  }, []);
  const refill = (value: string) => {
    chat.setDraft(value);
    input.current?.focus();
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
    setDraftCanvas(null);
    setHidden(new Set());
  }, [chat.selected]);
  const setLayout = (next: LayoutMode) => {
    setMode(next);
    setRatio(next === 'canvas' ? 0.35 : next === 'collab' ? 0.55 : 0.5);
  };
  const header = (
    <>
      <WebActivity scope={scope} onOpen={chat.choose} />
      <SelectedRunReview
        renderContext={chat.local ? run => <DesktopRunContext run={run} /> : undefined}
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
        <input
          key={chat.selected}
          className="min-w-0 truncate text-sm font-medium text-slate-800 dark:text-slate-100"
          aria-label={chat.label('Conversation title', '会话标题')}
          defaultValue={chat.selectedRow.title}
          disabled={chat.busy || !scope.commands.includes('chat-rename')}
          title={chat.selectedRow.title}
          onBlur={(event) => {
            const value = event.target.value.trim();
            if (value && value !== chat.selectedRow?.title) void chat.rename(value);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') event.currentTarget.blur();
          }}
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
          welcome={null}
          render={(message) => <WebChatMessage message={message} chat={chat} refill={refill} openCode={openCode} hide={id => setHidden(current => new Set([...current, id]))} />}
          hidden={hidden}
        >
          <InteractionPanel
            conversation={chat.selected}
            enabled={
              chat.selectedRow?.execution_target === 'cloud' &&
              scope.commands.includes('chat-interactions')
            }
            active={!!chat.run}
            desktop={false}
            emptyActivity={!chat.loading && !chat.messages.length ? <EmptyConversation /> : null}
            section={mode === 'canvas' ? 'activity' : 'all'}
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
          count={chat.messages.length}
          running={!!chat.run}
        />
      }
      actions={<ChatLayoutSelector mode={mode} setMode={setLayout} hasWorkspace={!!workspace} />}
    />
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
            onSplitRatioChange={setRatio}
            statusBar={status}
            handleAccentColor={
              mode === 'canvas' ? 'violet' : mode === 'task' ? 'purple' : 'primary'
            }
            rightContent={
              mode === 'task' ? (
                <SignedTaskList conversation={chat.selected} active={!!chat.run} />
              ) : mode === 'canvas' ? (
                <SignedCanvas
                  scope={scope}
                  chat={chat}
                  draft={draftCanvas}
                  change={setDraftCanvas}
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
  const instance = createInstance();
  await instance.init({
    lng,
    resources: { [lng]: { translation: lng === 'zh' ? chinese : english } },
    interpolation: { escapeValue: false },
  });
  createRoot(document.getElementById('root')!).render(
    <I18nextProvider i18n={instance}>
      <PageTheme scope={scope} />
    </I18nextProvider>
  );
}
function PageTheme({ scope }: { scope: RichPageContext }) {
  const dark = usePageDarkMode();
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
