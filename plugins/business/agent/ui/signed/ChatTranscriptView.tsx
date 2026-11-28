import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowDown } from "lucide-react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { mountTranscriptViewport } from "../../../../../agi-stack/packages/plugin-slots/src/ui/transcriptViewport";
import type { Chat } from "./useChat";
import type { TranscriptRow } from "./transcriptRows";

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

/** One positioned entry of the transcript: a message, reasoning, tool steps, a request card, an error or a folded turn. */
export interface TranscriptItem {
  id: string;
  kind: TranscriptRow["kind"] | "folded";
  node: ReactNode;
}

export function Transcript({
  chat,
  items,
  welcome,
  search,
  older,
  settled,
  above,
  children,
}: {
  children?: ReactNode;
  chat: Chat;
  items: readonly TranscriptItem[];
  welcome: ReactNode;
  /** Reads the page before the loaded history, with the tool steps of that page. */
  older: () => void;
  /** Whether the tool steps of the loaded history have been read. */
  settled: boolean;
  /** Content above the messages, as the pinned messages of the original transcript. */
  above?: (jump: (id: string) => void) => ReactNode;
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
  const loadOlder = useRef(older);
  loadOlder.current = older;
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
  }, [chat.messages, items]);
  // Like the original transcript, earlier history is read when the reader reaches
  // the top, and at once while the loaded rows do not fill the viewport. The rows
  // are measured once the tool steps of the page are in, and a page is asked for
  // once: one that comes back empty ends the history.
  const cursor = chat.cursor;
  const reading = chat.loading || !settled;
  const busy = chat.busy;
  const asked = useRef<typeof cursor>();
  useEffect(() => {
    const element = viewport.current;
    if (
      !cursor ||
      reading ||
      busy ||
      asked.current === cursor ||
      !element ||
      element.scrollHeight > element.clientHeight + 10
    )
      return;
    asked.current = cursor;
    loadOlder.current();
  }, [cursor, reading, busy, items]);
  return (
    <>
      {search?.(
        (id, located) =>
          controller.current?.navigate(id, located) ?? (() => {}),
      )}
      <div className="flex h-full min-h-0 flex-col">
        {above?.((id) => {
          controller.current?.navigate(id, () => {});
        })}
        <div className="relative min-h-0 flex-1">
        <div
          data-testid="message-container"
          className="chat-history-viewport"
          ref={viewport}
          role="log" aria-live="polite"
          tabIndex={0}
          aria-busy={chat.loading}
        >
          <div>
            {items.length
              ? items.map((item) => (
                  <div key={item.id} data-timeline-anchor-id={item.id} data-msg-id={item.id} data-row-kind={item.kind}>
                    {item.node}
                  </div>
                ))
              : !chat.loading && welcome}
            {children}
          </div>
        </div>
        {/* The floating control of the original transcript for returning to the latest message. */}
        {!following && (
          <button
            type="button"
            onClick={() => controller.current?.followLatest()}
            className="absolute bottom-6 right-6 z-10 flex h-11 w-11 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-600 shadow-md transition-[color,background-color,box-shadow] duration-150 hover:bg-slate-50 hover:shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
            title={chat.label("Jump to latest", "跳至最新")}
            aria-label={chat.label("Jump to latest", "跳至最新")}
          >
            <ArrowDown size={20} />
          </button>
        )}
        </div>
      </div>
    </>
  );
}
