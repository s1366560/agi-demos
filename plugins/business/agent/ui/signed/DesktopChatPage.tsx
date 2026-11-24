import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import english from "../web/locales/en-US.json";
import chinese from "../web/locales/zh-CN.json";
import { InteractionPanel } from "./InteractionPanel";
import { AttachmentPicker } from "./AttachmentPicker";
import { useEffect, useState } from "react";
import { MagnifyingGlassIcon } from "@radix-ui/react-icons";
import { ConversationSearch } from "../desktop/chat/ConversationSearch";
import { searchEn, searchZh } from "../desktop/chat/searchMessages";
import { createRoot } from "react-dom/client";
import { ArrowUpIcon, PlusIcon, StopIcon } from "@radix-ui/react-icons";
import { Button, Select, TextField, Theme } from "@radix-ui/themes";
import { ChatDraftInput } from "../desktop/chat/ChatDraftInput";
import { TranscriptMessageFrame } from "../desktop/chat/TranscriptMessageFrame";
import { SessionWelcome } from "../desktop/chat/SessionWelcome";
import { useChat, type Target } from "./useChat";
import { Answer, Transcript } from "./ChatTranscriptView";
import type { RichPageContext } from "../../../../../sdk/memstack-plugin-sdk/src/pageRuntime";
import "./desktopChat.css";

function DesktopChatPage({ scope }: { scope: RichPageContext }) {
  const chat = useChat(scope);
  const label = chat.label;
  const [searchOpen, setSearchOpen] = useState(false);
  const messages = scope.locale.startsWith("zh") ? searchZh : searchEn;
  useEffect(() => {
    const onShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "f") {
        event.preventDefault();
        setSearchOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onShortcut);
    return () => window.removeEventListener("keydown", onShortcut);
  }, []);
  const t = (key: string, values?: Record<string, string | number>) =>
    (messages[key] ?? key).replace(
      /\{(\w+)\}/g,
      (match: string, name: string) => String(values?.[name] ?? match),
    );
  const canWrite = chat.selectedRow
    ? chat.writable
    : chat.target === "cloud" || chat.hasDevice;
  const title = label("Conversation title", "会话标题");
  const placeholder = label(
    "Describe the task you want to run…",
    "描述要执行的任务…",
  );
  return (
    <Theme accentColor="green" grayColor="slate">
      <div className="agent-session-layout">
        <aside className="agent-session-list">
          <div className="agent-session-creation">
            <Select.Root
              value={chat.target}
              onValueChange={(value) => chat.setTarget(value as Target)}
            >
              <Select.Trigger
                aria-label={label(
                  "Execution location for new conversations",
                  "新会话执行位置",
                )}
              />
              <Select.Content>
                <Select.Item value="cloud">
                  {label("Cloud", "云端")}
                </Select.Item>
                <Select.Item value="local">
                  {label("Local", "本机")}
                </Select.Item>
              </Select.Content>
            </Select.Root>
            <Button
              variant="ghost"
              aria-label={label("New conversation", "新会话")}
              disabled={chat.busy}
              onClick={chat.create}
            >
              <PlusIcon />
            </Button>
          </div>
          {chat.list.map((row) => (
            <Button
              key={row.id}
              variant={chat.selected === row.id ? "soft" : "ghost"}
              disabled={chat.busy}
              onClick={() => chat.choose(row.id)}
            >
              {row.title}
            </Button>
          ))}
        </aside>
        <main className="session-workspace-thread">
          <section className="pane-shell chat-shell session-chat-narrative">
            {chat.selectedRow && (
              <header className="pane-head">
                <TextField.Root
                  key={chat.selected}
                  variant="soft"
                  aria-label={title}
                  defaultValue={chat.selectedRow.title}
                  disabled={chat.busy}
                  onBlur={(e) => {
                    const title = e.target.value.trim();
                    if (title && title !== chat.selectedRow?.title)
                      void chat.rename(title);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") e.currentTarget.blur();
                  }}
                />
                <Button
                  variant="ghost"
                  aria-label={t("chat.search.label")}
                  onClick={() => setSearchOpen((open) => !open)}
                >
                  <MagnifyingGlassIcon />
                </Button>
              </header>
            )}
            <Transcript
              chat={chat}
              search={(navigate) => (
                <ConversationSearch
                  t={t}
                  visible={searchOpen}
                  items={chat.messages.map((message) => ({
                    ...message,
                    type: message.role,
                  }))}
                  onClose={() => setSearchOpen(false)}
                  onNavigate={navigate}
                />
              )}
              welcome={
                <SessionWelcome
                  title={label(
                    "This session has no activity yet",
                    "此会话还没有活动",
                  )}
                  description={label(
                    "Send an instruction below to start planning.",
                    "在下方发送指令开始规划。",
                  )}
                />
              }
              render={(message) => (
                <TranscriptMessageFrame
                  kind={message.role === "user_message" ? "user" : "agent"}
                  label={
                    message.role === "user_message"
                      ? label("You", "你")
                      : "Agent"
                  }
                  className="session-message"
                >
                  <div className="transcript-content">
                    <Answer text={message.content} />
                  </div>
                </TranscriptMessageFrame>
              )}
            >
              <InteractionPanel
                conversation={chat.selected}
                enabled={
                  chat.selectedRow?.execution_target === "cloud" &&
                  scope.commands.includes("chat-interactions")
                }
                active={!!chat.run}
                desktop={true}
              />
            </Transcript>
            {chat.error && <p role="alert">{chat.error}</p>}
            {canWrite ? (
              <form
                className="chat-composer"
                onSubmit={(e) => {
                  e.preventDefault();
                  void chat.send();
                }}
              >
                <div className="session-composer-editor">
                  <AttachmentPicker
                    chat={chat}
                    enabled={
                      scope.commands.includes("chat-upload") &&
                      (chat.selectedRow?.execution_target ?? chat.target) ===
                        "cloud"
                    }
                  />
                  <ChatDraftInput
                    value={chat.draft}
                    aria-label={placeholder}
                    placeholder={placeholder}
                    onChange={(e) => chat.setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (
                        e.key === "Enter" &&
                        !e.shiftKey &&
                        !e.nativeEvent.isComposing
                      ) {
                        e.preventDefault();
                        void chat.send();
                      }
                    }}
                  />
                  <div className="session-composer-toolbar">
                    {chat.run ? (
                      <Button
                        color="red"
                        type="button"
                        className="send-pill"
                        disabled={chat.stopping}
                        aria-label={label("Stop", "停止")}
                        onClick={chat.stop}
                      >
                        <StopIcon />
                      </Button>
                    ) : (
                      <Button
                        color="green"
                        type="button"
                        onClick={() => void chat.send()}
                        className="send-pill"
                        disabled={chat.busy || !chat.draft.trim()}
                        aria-label={label("Send message", "发送消息")}
                      >
                        <ArrowUpIcon />
                      </Button>
                    )}
                  </div>
                </div>
              </form>
            ) : (
              <p>
                {label(
                  "Approve this release on the device to send local messages.",
                  "请在设备上批准当前版本后发送本机消息。",
                )}
              </p>
            )}
          </section>
        </main>
      </div>
    </Theme>
  );
}

void window.memstack.getContext().then(async (scope) => {
  const lng = scope.locale.startsWith("zh") ? "zh" : "en";
  const instance = createInstance();
  await instance.init({
    lng,
    resources: { [lng]: { translation: lng === "zh" ? chinese : english } },
    interpolation: { escapeValue: false },
  });
  createRoot(document.getElementById("root")!).render(
    <I18nextProvider i18n={instance}>
      <DesktopChatPage scope={scope} />
    </I18nextProvider>,
  );
});
