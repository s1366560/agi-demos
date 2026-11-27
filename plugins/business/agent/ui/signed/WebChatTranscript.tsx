import type { ReactNode } from "react";
import type { RichPageContext } from "../../../../../sdk/memstack-plugin-sdk/src/pageRuntime";

import { ExecutionTimeline } from "../web/transcript/timeline/ExecutionTimeline";
import { JitContextCard } from "../web/transcript/timeline/JitContextCard";
import { MemoryCapturedStep } from "../web/transcript/timeline/MemoryRecalledStep";
import type {
  MemoryCapturedTimelineEvent,
  MemoryRecalledTimelineEvent,
} from "../../../../../web/src/types/agent";
import {
  InlineEvent,
  Thought,
  type InlineEventFields,
} from "../web/transcript/messageBubble/inlineEvents";
import { TurnPlaceholderRow } from "../web/transcript/message/TurnPlaceholderRow";
import { MESSAGE_MAX_WIDTH_CLASSES } from "../web/chat/styles";

import type { TranscriptItem } from "./ChatTranscriptView";
import type { Chat } from "./useChat";
import type { TranscriptEntry } from "./foldTurns";
import { hasBubble, type TranscriptRow } from "./transcriptRows";
import { WebChatMessage, type MessageFold } from "./WebChatMessage";
import { SignedArtifactCard } from "./SignedArtifactCard";

/** The text column of a message, without its avatar, so that steps align with message text. */
function TextColumn({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-3 pb-1">
      <div className="w-8 shrink-0" />
      <div className={`flex-1 min-w-0 ${MESSAGE_MAX_WIDTH_CLASSES}`}>
        {children}
      </div>
    </div>
  );
}

/**
 * Render the shown entries of a conversation with the transcript pieces of the
 * original workbench: reasoning, tool steps, requests and errors sit where they
 * happened, a folded turn is one placeholder, and an answer can be pinned. Only
 * the latest group of steps is expanded, as in a transcript that is still running.
 */
export function chatTranscriptItems({
  entries,
  chat,
  streaming,
  refill,
  openCode,
  hide,
  pinned,
  onPin,
  foldFor,
  onExpand,
  saveTemplate,
  scope,
}: {
  entries: readonly TranscriptEntry[];
  chat: Chat;
  scope: RichPageContext;
  streaming: boolean;
  refill: (value: string) => void;
  openCode: (text: string, language?: string) => void;
  hide: (id: string) => void;
  /** Ids of the answers pinned above the transcript. */
  pinned: ReadonlySet<string>;
  onPin: (id: string) => void;
  /** The turn a user message opens, when what answers it can be folded. */
  foldFor: (row: TranscriptRow) => MessageFold | undefined;
  onExpand: (turnId: string) => void;
  /** Keeps an answer as a prompt template, when the page may. */
  saveTemplate?: (content: string, title: string, category: string) => Promise<void>;
}): TranscriptItem[] {
  let current = -1;
  entries.forEach((entry, index) => {
    if (entry.kind === "row" && entry.row.kind === "steps") current = index;
  });
  const last = entries.length - 1;
  return entries.map((entry, index): TranscriptItem => {
    if (entry.kind === "folded")
      return {
        id: `folded:${entry.turnId}`,
        kind: "folded",
        node: (
          <TurnPlaceholderRow
            hiddenCount={entry.hiddenCount}
            onExpand={() => {
              onExpand(entry.turnId);
            }}
          />
        ),
      };
    const row = entry.row;
    const item = (node: ReactNode): TranscriptItem => ({
      id: row.id,
      kind: row.kind,
      node,
    });
    switch (row.kind) {
      case "message": {
        const answer = row.message.role === "assistant_message";
        // As in the original transcript, an answer without text is drawn while its
        // turn still runs, or for the usage it carries.
        if (answer && !hasBubble(row.message, streaming && index === last))
          return item(null);
        const fold = answer ? undefined : foldFor(row);
        return item(
          <WebChatMessage
            message={row.message}
            chat={chat}
            refill={refill}
            openCode={openCode}
            hide={hide}
            {...(answer && pinned.has(row.id) ? { pinned: true } : {})}
            {...(answer ? { onPin: () => onPin(row.id) } : {})}
            {...(fold ? { fold } : {})}
            {...(answer && saveTemplate ? { saveTemplate } : {})}
          />,
        );
      }
      case "thought":
        return item(
          <Thought content={row.content} timestamp={row.timestamp} />,
        );
      case "steps":
        return item(
          <TextColumn>
            <ExecutionTimeline
              steps={row.steps}
              isStreaming={streaming && index === current}
              defaultCollapsed={index !== current}
            />
          </TextColumn>,
        );
      case "event":
        return item(
          <TextColumn>
            <InlineEvent event={row.event as unknown as InlineEventFields} />
          </TextColumn>,
        );
      case "artifact":
        return item(
          <SignedArtifactCard
            event={row.event}
            conversation={chat.selected}
            scope={scope}
          />,
        );
      case "memory":
        return item(
          <TextColumn>
            {row.event.type === "memory_captured" ? (
              <MemoryCapturedStep
                event={row.event as unknown as MemoryCapturedTimelineEvent}
              />
            ) : (
              <JitContextCard
                event={row.event as unknown as MemoryRecalledTimelineEvent}
                conversationId={chat.selected}
              />
            )}
          </TextColumn>,
        );
    }
  });
}
