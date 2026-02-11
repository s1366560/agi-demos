/**
 * Export conversation timeline as Markdown file.
 *
 * Converts TimelineEvent[] to readable Markdown and triggers
 * a browser download.
 */

import type { TimelineEvent } from '@/types/agent';

function formatTimestamp(ts: number): string {
  return new Date(ts).toLocaleString();
}

/**
 * Convert a timeline to Markdown text.
 */
export function timelineToMarkdown(timeline: TimelineEvent[], title?: string): string {
  const lines: string[] = [];
  lines.push(`# ${title || 'Conversation Export'}`);
  lines.push('');
  lines.push(`> Exported at ${new Date().toISOString()}`);
  lines.push('');
  lines.push('---');
  lines.push('');

  for (const event of timeline) {
    switch (event.type) {
      case 'user_message':
        lines.push(`## 🧑 User`);
        lines.push(`*${formatTimestamp(event.timestamp)}*`);
        lines.push('');
        lines.push(event.content);
        lines.push('');
        break;

      case 'assistant_message':
        lines.push(`## 🤖 Assistant`);
        lines.push(`*${formatTimestamp(event.timestamp)}*`);
        lines.push('');
        lines.push(event.content);
        lines.push('');
        break;

      case 'thought':
        lines.push(`<details><summary>💭 Thinking</summary>`);
        lines.push('');
        lines.push(event.content);
        lines.push('');
        lines.push('</details>');
        lines.push('');
        break;

      case 'act':
        lines.push(`> 🔧 **Tool Call**: \`${event.toolName}\``);
        if (event.toolInput && Object.keys(event.toolInput).length > 0) {
          lines.push('> ```json');
          lines.push(`> ${JSON.stringify(event.toolInput, null, 2).split('\n').join('\n> ')}`);
          lines.push('> ```');
        }
        lines.push('');
        break;

      case 'observe':
        lines.push(`> 📋 **Result** (${event.toolName})${event.isError ? ' ❌ Error' : ''}`);
        if (event.toolOutput) {
          const output = event.toolOutput.length > 500
            ? event.toolOutput.slice(0, 500) + '...(truncated)'
            : event.toolOutput;
          lines.push('> ```');
          lines.push(`> ${output.split('\n').join('\n> ')}`);
          lines.push('> ```');
        }
        lines.push('');
        break;

      default:
        // Skip non-essential event types (text_delta, step_start, etc.)
        break;
    }
  }

  return lines.join('\n');
}

/**
 * Download conversation as a .md file.
 */
export function downloadConversationMarkdown(
  timeline: TimelineEvent[],
  title?: string,
  filename?: string,
): void {
  const md = timelineToMarkdown(timeline, title);
  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename || `conversation-${Date.now()}.md`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Convert a timeline to styled HTML for PDF rendering.
 */
function timelineToHtml(timeline: TimelineEvent[], title?: string): string {
  const lines: string[] = [];
  lines.push(
    `<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 700px; margin: 0 auto; color: #1e293b;">`,
  );
  lines.push(
    `<h1 style="font-size: 20px; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin-bottom: 16px;">${escapeHtml(title || 'Conversation Export')}</h1>`,
  );
  lines.push(
    `<p style="font-size: 11px; color: #94a3b8; margin-bottom: 24px;">Exported at ${new Date().toISOString()}</p>`,
  );

  for (const event of timeline) {
    switch (event.type) {
      case 'user_message':
        lines.push(
          `<div style="margin-bottom: 16px; padding: 12px 16px; background: #f1f5f9; border-radius: 8px;">`,
        );
        lines.push(
          `<div style="font-size: 11px; color: #64748b; margin-bottom: 4px; font-weight: 600;">User &mdash; ${formatTimestamp(event.timestamp)}</div>`,
        );
        lines.push(
          `<div style="font-size: 14px; white-space: pre-wrap;">${escapeHtml(event.content)}</div>`,
        );
        lines.push(`</div>`);
        break;
      case 'assistant_message':
        lines.push(
          `<div style="margin-bottom: 16px; padding: 12px 16px; background: #eff6ff; border-left: 3px solid #3b82f6; border-radius: 4px;">`,
        );
        lines.push(
          `<div style="font-size: 11px; color: #3b82f6; margin-bottom: 4px; font-weight: 600;">Assistant &mdash; ${formatTimestamp(event.timestamp)}</div>`,
        );
        lines.push(
          `<div style="font-size: 14px; white-space: pre-wrap;">${escapeHtml(event.content)}</div>`,
        );
        lines.push(`</div>`);
        break;
      case 'thought':
        lines.push(
          `<div style="margin-bottom: 8px; padding: 8px 12px; background: #fefce8; border-radius: 4px; font-size: 12px; color: #854d0e;">`,
        );
        lines.push(
          `<strong>Thinking:</strong> ${escapeHtml(event.content).slice(0, 300)}${event.content.length > 300 ? '...' : ''}`,
        );
        lines.push(`</div>`);
        break;
      case 'act':
        lines.push(
          `<div style="margin-bottom: 4px; padding: 6px 12px; background: #f0fdf4; border-radius: 4px; font-size: 12px; color: #166534;">`,
        );
        lines.push(
          `<strong>Tool:</strong> <code>${escapeHtml(event.toolName || '')}</code>`,
        );
        lines.push(`</div>`);
        break;
      case 'observe':
        if (event.toolOutput) {
          const output =
            event.toolOutput.length > 300
              ? event.toolOutput.slice(0, 300) + '...'
              : event.toolOutput;
          lines.push(
            `<div style="margin-bottom: 12px; padding: 6px 12px; background: #f8fafc; border-radius: 4px; font-size: 11px; font-family: monospace; color: #475569; overflow: hidden;">`,
          );
          lines.push(`${escapeHtml(output)}`);
          lines.push(`</div>`);
        }
        break;
    }
  }

  lines.push(`</div>`);
  return lines.join('\n');
}

/**
 * Download conversation as a PDF file.
 */
export async function downloadConversationPdf(
  timeline: TimelineEvent[],
  title?: string,
  filename?: string,
): Promise<void> {
  const { default: html2pdf } = await import('html2pdf.js');

  const html = timelineToHtml(timeline, title);
  const container = document.createElement('div');
  container.innerHTML = html;
  container.style.position = 'absolute';
  container.style.left = '-9999px';
  document.body.appendChild(container);

  try {
    await html2pdf()
      .set({
        margin: [10, 10, 10, 10],
        filename: filename || `conversation-${Date.now()}.pdf`,
        html2canvas: { scale: 2, useCORS: true },
        jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
        pagebreak: { mode: ['avoid-all', 'css', 'legacy'] },
      } as any)
      .from(container)
      .save();
  } finally {
    document.body.removeChild(container);
  }
}
