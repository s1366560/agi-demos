import { useEffect, useRef, useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { mountTranscriptViewport } from "../../../../../agi-stack/packages/plugin-slots/src/ui/transcriptViewport";
import type { Chat, Message } from "./useChat";

export function Answer({
  text,
  components,
}: {
  text: string;
  components?: Components;
}) {
  return (
    <ReactMarkdown
      skipHtml
      remarkPlugins={[remarkGfm]}
      components={{
        ...components,
        img: ({ alt }) => <span>{alt}</span>,
        a: ({ children }) => <span>{children}</span>,
      }}
    >
      {text}
    </ReactMarkdown>
  );
}

export function Transcript({
  chat,
  render,
  welcome,
  search,
  hidden,
  children,
}: {
  children?: ReactNode;
  chat: Chat;
  render: (message: Message) => ReactNode;
  welcome: ReactNode;
  hidden?: ReadonlySet<string>;
  search?: (
    navigate: (
      id: string,
      located: (element: HTMLElement) => void,
    ) => () => void,
  ) => ReactNode;
}) {
  const readingHistory = useRef(false);
  readingHistory.current = !chat.local && !chat.run && !chat.loading;
  const viewport = useRef<HTMLDivElement>(null);
  const controller = useRef<ReturnType<typeof mountTranscriptViewport> | null>(
    null,
  );
  const loadOlder = useRef(chat.older);
  loadOlder.current = chat.older;
  const [following, setFollowing] = useState(true);
  useEffect(() => {
    if (!viewport.current) return;
    const current = mountTranscriptViewport(
      viewport.current,
      setFollowing,
      () => void loadOlder.current(),
      () => readingHistory.current,
    );
    controller.current = current;
    return () => {
      current.dispose();
      controller.current = null;
    };
  }, [chat.selected]);
  useEffect(() => {
    controller.current?.schedule();
  }, [chat.messages]);
  const messages = hidden ? chat.messages.filter(message => !hidden.has(message.id)) : chat.messages;
  return (
    <>
      {search?.(
        (id, located) =>
          controller.current?.navigate(id, located) ?? (() => {}),
      )}
      <div
        data-testid="message-container"
        className="chat-history-viewport"
        ref={viewport}
        role="log" aria-live="polite"
        tabIndex={0}
        aria-busy={chat.loading}
      >
        <div>
          {chat.cursor && (
            <button onClick={() => void chat.older()}>
              {chat.label("Load older messages", "加载更早消息")}
            </button>
          )}
          {messages.length
            ? messages.map((message) => (
                <div key={message.id} data-timeline-anchor-id={message.id} data-msg-id={message.id}>
                  {render(message)}
                </div>
              ))
            : !chat.loading && welcome}
          {children}
        </div>
      </div>
      {!following && (
        <button onClick={() => controller.current?.followLatest()}>
          {chat.label("Jump to latest", "跳至最新")}
        </button>
      )}
    </>
  );
}
