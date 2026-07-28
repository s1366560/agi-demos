import type { AgentTimelineItem } from '../../types';

const SUPPORTED_EXPORT_EVENT_TYPES = new Set([
  'user_message',
  'assistant_message',
  'thought',
  'act',
  'observe',
] as const);

type ConversationExportEventType =
  | 'user_message'
  | 'assistant_message'
  | 'thought'
  | 'act'
  | 'observe';

export type ConversationExportEvent = {
  type: ConversationExportEventType;
  timestampMs: number;
  content: string;
  toolName: string;
  toolInput: string;
  toolOutput: string;
  isError: boolean;
};

export type ConversationExportSnapshot = {
  conversationId: string;
  title: string;
  events: ConversationExportEvent[];
};

type ConversationExportRenderOptions = {
  exportedAt?: Date;
  formatTimestamp?: (timestampMs: number) => string;
};

function stringifyExportValue(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value === null || value === undefined) return '';
  try {
    return JSON.stringify(value, null, 2) ?? '';
  } catch {
    return String(value);
  }
}

function itemTimestampMs(item: AgentTimelineItem): number {
  if (Number.isFinite(item.eventTimeUs)) return Math.floor(item.eventTimeUs / 1_000);
  if (typeof item.timestamp === 'number' && Number.isFinite(item.timestamp)) {
    return item.timestamp;
  }
  return 0;
}

function isSupportedExportEventType(type: string): type is ConversationExportEventType {
  return SUPPORTED_EXPORT_EVENT_TYPES.has(type as ConversationExportEventType);
}

export function createConversationExportSnapshot({
  conversationId,
  title,
  items,
}: {
  conversationId: string;
  title: string;
  items: readonly AgentTimelineItem[];
}): ConversationExportSnapshot {
  return {
    conversationId,
    title,
    events: items.flatMap((item) => {
      if (!isSupportedExportEventType(item.type)) return [];
      return [
        {
          type: item.type,
          timestampMs: itemTimestampMs(item),
          content: item.content ?? '',
          toolName: item.toolName ?? '',
          toolInput: stringifyExportValue(item.toolInput),
          toolOutput: stringifyExportValue(item.toolOutput),
          isError: item.isError === true,
        },
      ];
    }),
  };
}

export function cloneConversationExportSnapshot(
  snapshot: ConversationExportSnapshot,
): ConversationExportSnapshot {
  return {
    conversationId: snapshot.conversationId,
    title: snapshot.title,
    events: snapshot.events.map((event) => ({ ...event })),
  };
}

export function conversationExportFilename(
  snapshot: ConversationExportSnapshot,
  format: 'markdown' | 'pdf',
): string {
  return `conversation-${snapshot.conversationId || 'export'}.${
    format === 'markdown' ? 'md' : 'pdf'
  }`;
}

function renderContext(options?: ConversationExportRenderOptions) {
  return {
    exportedAt: options?.exportedAt ?? new Date(),
    formatTimestamp:
      options?.formatTimestamp ?? ((timestampMs: number) => new Date(timestampMs).toLocaleString()),
  };
}

export function conversationExportToMarkdown(
  snapshot: ConversationExportSnapshot,
  options?: ConversationExportRenderOptions,
): string {
  const { exportedAt, formatTimestamp } = renderContext(options);
  const lines: string[] = [
    '# Conversation Export',
    '',
    `> Exported at ${exportedAt.toISOString()}`,
    '',
    '---',
    '',
  ];

  for (const event of snapshot.events) {
    switch (event.type) {
      case 'user_message':
        lines.push('## User');
        lines.push(`*${formatTimestamp(event.timestampMs)}*`);
        lines.push('');
        lines.push(event.content);
        lines.push('');
        break;
      case 'assistant_message':
        lines.push('## Assistant');
        lines.push(`*${formatTimestamp(event.timestampMs)}*`);
        lines.push('');
        lines.push(event.content);
        lines.push('');
        break;
      case 'thought':
        lines.push('<details><summary>Thinking</summary>');
        lines.push('');
        lines.push(event.content);
        lines.push('');
        lines.push('</details>');
        lines.push('');
        break;
      case 'act':
        lines.push(`> **Tool Call**: \`${event.toolName}\``);
        if (event.toolInput.length > 0 && event.toolInput !== '{}') {
          lines.push('> ```json');
          lines.push(`> ${event.toolInput.split('\n').join('\n> ')}`);
          lines.push('> ```');
        }
        lines.push('');
        break;
      case 'observe': {
        lines.push(`> **Result** (${event.toolName})${event.isError ? ' Error' : ''}`);
        if (event.toolOutput) {
          const output =
            event.toolOutput.length > 500
              ? `${event.toolOutput.slice(0, 500)}...(truncated)`
              : event.toolOutput;
          lines.push('> ```');
          lines.push(`> ${output.split('\n').join('\n> ')}`);
          lines.push('> ```');
        }
        lines.push('');
        break;
      }
    }
  }

  return lines.join('\n');
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Exported HTML must render standalone, without the app's stylesheets, so the
// palette below is intentionally hardcoded to a fixed light scheme instead of
// referencing --desktop-* tokens; exports stay theme-neutral by design.
export function conversationExportToHtml(
  snapshot: ConversationExportSnapshot,
  options?: ConversationExportRenderOptions,
): string {
  const { exportedAt, formatTimestamp } = renderContext(options);
  const lines: string[] = [
    `<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 700px; margin: 0 auto; color: #1e293b;">`,
    `<h1 style="font-size: 20px; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin-bottom: 16px;">Conversation Export</h1>`,
    `<p style="font-size: 11px; color: #94a3b8; margin-bottom: 24px;">Exported at ${exportedAt.toISOString()}</p>`,
  ];

  for (const event of snapshot.events) {
    switch (event.type) {
      case 'user_message':
        lines.push(
          `<div style="margin-bottom: 16px; padding: 12px 16px; background: #f1f5f9; border-radius: 8px;">`,
        );
        lines.push(
          `<div style="font-size: 11px; color: #64748b; margin-bottom: 4px; font-weight: 600;">User - ${formatTimestamp(event.timestampMs)}</div>`,
        );
        lines.push(
          `<div style="font-size: 14px; white-space: pre-wrap;">${escapeHtml(event.content)}</div>`,
        );
        lines.push('</div>');
        break;
      case 'assistant_message':
        lines.push(
          `<div style="margin-bottom: 16px; padding: 12px 16px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px;">`,
        );
        lines.push(
          `<div style="font-size: 11px; color: #2563eb; margin-bottom: 4px; font-weight: 600;">Assistant - ${formatTimestamp(event.timestampMs)}</div>`,
        );
        lines.push(
          `<div style="font-size: 14px; white-space: pre-wrap;">${escapeHtml(event.content)}</div>`,
        );
        lines.push('</div>');
        break;
      case 'thought':
        lines.push(
          `<div style="margin-bottom: 8px; padding: 8px 12px; background: #fefce8; border-radius: 4px; font-size: 12px; color: #854d0e;">`,
        );
        lines.push(
          `<strong>Thinking:</strong> ${escapeHtml(event.content).slice(0, 300)}${event.content.length > 300 ? '...' : ''}`,
        );
        lines.push('</div>');
        break;
      case 'act':
        lines.push(
          `<div style="margin-bottom: 4px; padding: 6px 12px; background: #f0fdf4; border-radius: 4px; font-size: 12px; color: #166534;">`,
        );
        lines.push(`<strong>Tool:</strong> <code>${escapeHtml(event.toolName)}</code>`);
        lines.push('</div>');
        break;
      case 'observe': {
        if (!event.toolOutput) break;
        const output =
          event.toolOutput.length > 300
            ? `${event.toolOutput.slice(0, 300)}...`
            : event.toolOutput;
        lines.push(
          `<div style="margin-bottom: 12px; padding: 6px 12px; background: #f8fafc; border-radius: 4px; font-size: 11px; font-family: monospace; color: #475569; overflow: hidden;">`,
        );
        lines.push(escapeHtml(output));
        lines.push('</div>');
        break;
      }
    }
  }

  lines.push('</div>');
  return lines.join('\n');
}
