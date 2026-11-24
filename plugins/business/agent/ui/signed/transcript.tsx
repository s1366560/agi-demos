import React from 'react';
import { createRoot, type Root } from 'react-dom/client';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export { mountTranscriptViewport } from '../../../../../agi-stack/packages/plugin-slots/src/ui/transcriptViewport';

const roots = new Map<HTMLElement, Root>();

export function renderAnswer(element: HTMLElement, text: string) {
  const root = roots.get(element) ?? createRoot(element);
  roots.set(element, root);
  root.render(
    <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={{
      // Attachments need an authorized resource handle before they can be opened.
      img: ({ alt }) => <span>{alt}</span>,
      a: ({ children }) => <span>{children}</span>,
    }}>{text}</ReactMarkdown>
  );
}

export function releaseAnswers() {
  for (const root of roots.values()) root.unmount();
  roots.clear();
}
