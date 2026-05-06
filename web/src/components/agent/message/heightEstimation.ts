/**
 * Height estimation utilities for the virtualized message list.
 * Better estimates reduce scroll jumping when items are measured for real.
 */

import type { GroupedItem } from './groupTimelineEvents';
import type { DisplayItem } from './turnFolding';

/**
 * Estimate item height for the virtualizer based on item type.
 */
export function estimateGroupedItemHeight(item: GroupedItem | DisplayItem): number {
  if (item.kind === 'turn-placeholder') {
    return 36;
  }
  if (item.kind === 'timeline') {
    return 80 + item.steps.length * 52;
  }
  if (item.kind === 'subagent') {
    const base = 60;
    const g = item.group;
    if (g.mode === 'parallel' && g.parallelInfo) return base + g.parallelInfo.taskCount * 36;
    if (g.mode === 'chain' && g.chainInfo) return base + g.chainInfo.steps.length * 40;
    return base + (g.summary ? 60 : 0);
  }
  const { event } = item;
  switch (event.type) {
    case 'user_message':
      return 100;
    case 'assistant_message': {
      const content = event.content || '';
      return estimateMarkdownHeight(content);
    }
    default:
      return 80;
  }
}

/**
 * Estimate rendered height of markdown content by analyzing structure.
 * Counts code blocks, line breaks, and text density for better accuracy.
 * More accurate estimates reduce virtualizer scroll jumping.
 */
export function estimateMarkdownHeight(content: string): number {
  if (!content) return 80;

  const LINE_HEIGHT = 24;
  const CODE_LINE_HEIGHT = 20;
  const BASE_PADDING = 60; // bubble chrome (avatar, margins, padding)
  let height = BASE_PADDING;

  // Count fenced code blocks and estimate their height
  const codeBlockRegex = /```[\s\S]*?```/g;
  let remaining = content;
  let match: RegExpExecArray | null;
  while ((match = codeBlockRegex.exec(content)) !== null) {
    const block = match[0];
    const lines = block.split('\n').length;
    // Code block: header(32) + lines + padding(24)
    height += 32 + lines * CODE_LINE_HEIGHT + 24;
    remaining = remaining.replace(block, '');
  }

  // Count lines in remaining non-code text
  const textLines = remaining.split('\n');
  for (const line of textLines) {
    const trimmed = line.trim();
    if (!trimmed) {
      height += 8; // empty line spacing
    } else if (trimmed.startsWith('#')) {
      height += 36; // heading
    } else if (trimmed.startsWith('|')) {
      height += 32; // table row
    } else if (trimmed.startsWith('- ') || trimmed.startsWith('* ') || /^\d+\./.test(trimmed)) {
      height += LINE_HEIGHT; // list item
    } else if (trimmed.startsWith('![')) {
      height += 200; // image placeholder
    } else if (trimmed.startsWith('> ')) {
      // Blockquote: estimate wrapped text + border/padding
      const quoteText = trimmed.slice(2);
      height += Math.max(1, Math.ceil(quoteText.length / 70)) * LINE_HEIGHT + 16;
    } else {
      // Regular text: wrap estimate (~80 chars per visual line)
      height += Math.max(1, Math.ceil(trimmed.length / 80)) * LINE_HEIGHT;
    }
  }

  // Add margin for markdown elements that expand (e.g. nested lists, tables with wide content)
  return Math.max(80, Math.round(height * 1.05));
}
