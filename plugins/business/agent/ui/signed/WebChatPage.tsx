import { MessageFileList } from '../web/chat/MessageFileList';
import { InteractionPanel } from './InteractionPanel';
import { AttachmentPicker } from './AttachmentPicker';
import { CodeBlock } from '../web/chat/CodeBlock';
import { MarkdownTable } from '../web/chat/MarkdownTable';
import { UserBubble, UserAvatar } from '../web/chat/UserBubble';
import { useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { Button, Input } from 'antd';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { Plus } from 'lucide-react';
import { EmptyState } from '../web/chat/EmptyState';
import { AssistantBubble } from '../web/chat/AssistantBubble';
import { ConversationRow } from '../web/chat/ConversationRow';
import { ChatDraftInput } from '../web/chat/ChatDraftInput';
import { SendControl } from '../web/chat/SendControl';
import { MARKDOWN_PROSE_CLASSES } from '../web/chat/styles';
import english from '../web/locales/en-US.json';
import chinese from '../web/locales/zh-CN.json';
import { Answer, Transcript } from './ChatTranscriptView';
import { useChat } from './useChat';
import type { RichPageContext } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import './webChat.css';

const markdownComponents = { pre: CodeBlock, table: MarkdownTable };

function WebChatPage({ scope }: { scope: RichPageContext }) {
  const chat = useChat(scope);
  const { pathname } = useLocation();
  useEffect(() => {
    if (pathname !== scope.pathname) chat.choose(decodeURIComponent(pathname.split('/').at(-1)!));
  }, [pathname, scope.pathname]);
  const canWrite = !chat.selected || chat.writable;
  const placeholder = chat.label('Message the agent…', '给智能体发送消息…');
  return (
    <div className="flex h-dvh min-h-0 bg-white text-slate-800 dark:bg-slate-950 dark:text-slate-100">
      <aside className="w-52 max-w-[30%] shrink-0 overflow-y-auto border-r border-slate-200 p-2">
        <Button block disabled={chat.busy} icon={<Plus size={16} />} onClick={chat.create}>
          {chat.label('New conversation', '新会话')}
        </Button>
        {chat.list.map((row) => (
          <ConversationRow
            key={row.id}
            href={'/agent/chat/' + encodeURIComponent(row.id)}
            disabled={chat.busy}
            primaryTitle={row.title}
            isActive={row.id === chat.selected}
            contextParts={[]}
            executionBadge={row.execution_target === 'local' ? chat.label('Local', '本机') : null}
          />
        ))}
      </aside>
      <main className="flex flex-1 flex-col min-w-0 min-h-0">
        {chat.selectedRow && (
          <header className="border-b border-slate-200 px-4 py-2">
            <Input
              key={chat.selected}
              variant="borderless"
              defaultValue={chat.selectedRow.title}
              aria-label={chat.label('Conversation title', '会话标题')}
              disabled={chat.busy}
              onBlur={(event) => {
                const title = event.target.value.trim();
                if (title && title !== chat.selectedRow?.title) void chat.rename(title);
              }}
              onPressEnter={(event) => event.currentTarget.blur()}
            />
          </header>
        )}
        <Transcript
          chat={chat}
          welcome={
            <EmptyState
              onNewConversation={chat.create}
              onSendPrompt={canWrite ? chat.send : undefined}
              showShortcutTips={false}
            />
          }
          render={(message) =>
            message.role === 'assistant_message' ? (
              <AssistantBubble>
                <div className={MARKDOWN_PROSE_CLASSES}>
                  <Answer components={markdownComponents} text={message.content} />
                </div>
              </AssistantBubble>
            ) : (
              <div className="flex items-end justify-end gap-3 w-full">
                <div className="max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
                  <UserBubble content={message.content} />
                  <MessageFileList files={message.files} />
                </div>
                <UserAvatar />
              </div>
            )
          }
        >
          <InteractionPanel
            conversation={chat.selected}
            enabled={
              chat.selectedRow?.execution_target === 'cloud' &&
              scope.commands.includes('chat-interactions')
            }
            active={!!chat.run}
            desktop={false}
          />
        </Transcript>
        {chat.error && (
          <div role="alert" className="px-4 text-red-700">
            {chat.error}
          </div>
        )}
        {canWrite ? (
          <div className="mx-auto mb-4 flex w-[94%] max-w-4xl items-end rounded-2xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800 p-2 shadow-sm">
            <AttachmentPicker
              chat={chat}
              enabled={
                scope.commands.includes('chat-upload') &&
                (chat.selectedRow?.execution_target ?? chat.target) === 'cloud'
              }
            />
            <ChatDraftInput
              aria-label={placeholder}
              placeholder={placeholder}
              value={chat.draft}
              onChange={(e) => chat.setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  void chat.send();
                }
              }}
            />
            <SendControl
              canSend={!!chat.draft.trim() && !chat.busy}
              isStreaming={!!chat.run}
              handleSend={() => void chat.send()}
              onAbort={() => void chat.stop()}
            />
          </div>
        ) : (
          <p className="p-4 text-slate-500">
            {chat.label(
              'Local conversations are read-only on the web.',
              '本机会话在 Web 端仅可回放。'
            )}
          </p>
        )}
      </main>
    </div>
  );
}

async function mount() {
  const scope = await window.memstack.getContext();
  const lng = scope.locale.startsWith('zh') ? 'zh' : 'en';
  const instance = createInstance();
  await instance.init({
    lng,
    resources: { [lng]: { translation: lng === 'zh' ? chinese : english } },
    interpolation: { escapeValue: false },
  });
  createRoot(document.getElementById('root')!).render(
    <I18nextProvider i18n={instance}>
      <MemoryRouter initialEntries={[scope.pathname]}>
        <WebChatPage scope={scope} />
      </MemoryRouter>
    </I18nextProvider>
  );
}
void mount();
