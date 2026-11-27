import type { TimelineEvent } from '../../../../../web/src/types/agent';
import {
  downloadConversationMarkdown,
  timelineToHtml,
  timelineToMarkdown,
} from '../../../../../web/src/utils/exportConversation';
import type { InteractionEvent } from './useInteractions';
import type { Chat } from './useChat';

type Placed = { eventTimeUs?: number; eventCounter?: number; timestamp?: number };

function position(row: Placed): [number, number] {
  return [row.eventTimeUs ?? (row.timestamp ?? 0) * 1000, row.eventCounter ?? 0];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * What the export reads of an event, as it reads the timeline of the original
 * workbench: text as text, and the arguments of a call as an object. The package
 * passes what a tool answered as it was, which is not always text.
 */
function exportable(row: Record<string, unknown>): Record<string, unknown> {
  const text = (value: unknown) =>
    typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value, null, 2);
  if (row.type === 'act') return { ...row, toolInput: isRecord(row.toolInput) ? row.toolInput : { input: row.toolInput } };
  if (row.type === 'observe') return { ...row, toolOutput: text(row.toolOutput) };
  return { ...row, content: text(row.content) };
}

/**
 * The conversation as the export of the original workbench reads it: messages,
 * reasoning and tool steps, in the order they happened.
 */
export function conversationTimeline(
  chat: Chat,
  events: readonly InteractionEvent[]
): TimelineEvent[] {
  const rows: object[] = [
    ...chat.messages.map((message) => exportable({ ...message, type: message.role })),
    ...chat.thoughts.map((thought) => exportable({ ...thought, type: 'thought' })),
    ...events
      .filter((event) => event.type === 'act' || event.type === 'observe')
      .map((event) => exportable({ ...event })),
  ];
  const placed = rows.map((row) => ({ row, at: position(row as Placed) }));
  placed.sort((a, b) => a.at[0] - b.at[0] || a.at[1] - b.at[1]);
  return placed.map(({ row }) => row) as unknown as TimelineEvent[];
}

/**
 * Export the conversation as a Markdown file or as a PDF, as the original workbench
 * does. The page cannot download by itself: it hands the file to the workbench,
 * which offers it to the user.
 */
export async function exportConversation(
  timeline: readonly TimelineEvent[],
  format: 'markdown' | 'pdf',
  title: string,
  filename: string
) {
  const save = window.memstack.saveFile;
  if (format === 'markdown') {
    if (save)
      await save(filename, { text: timelineToMarkdown([...timeline], title) }, 'text/markdown;charset=utf-8');
    else downloadConversationMarkdown([...timeline], title, filename);
    return;
  }
  // A document of the page cannot print itself: its frames are kept apart, which
  // is what printing needs. The workbench prints the same layout as its own.
  const print = window.memstack.printPdf;
  if (!print) throw new Error('page_export_unavailable');
  await print(filename, timelineToHtml([...timeline], title));
}
