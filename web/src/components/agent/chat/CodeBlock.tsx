/**
 * CodeBlock - Custom code block renderer for ReactMarkdown
 *
 * Adds "Copy" and "Open in Canvas" action buttons to fenced code blocks.
 * Detects mermaid language and renders diagrams via MermaidBlock.
 * Used as a `components.pre` override in ReactMarkdown instances.
 */

import { memo, useState, useCallback, useRef, useEffect } from 'react';

import { useTranslation } from 'react-i18next';
import { Copy, Check, PanelRight } from 'lucide-react';

import { useCanvasStore } from '@/stores/canvasStore';
import { useLayoutModeStore } from '@/stores/layoutMode';

import { MermaidBlock } from './MermaidBlock';

import type { ReactElement, ReactNode, HTMLAttributes } from 'react';

function extractCodeContent(children: ReactNode): { text: string; language?: string } {
  if (!children) return { text: '' };

  // ReactMarkdown wraps code in <pre><code className="language-xxx">...</code></pre>
  const child = Array.isArray(children) ? children[0] : children;
  if (child && typeof child === 'object' && 'props' in (child as ReactElement)) {
    const codeEl = child as ReactElement<HTMLAttributes<HTMLElement> & { children?: ReactNode }>;
    const className = (codeEl.props?.className as string) || '';
    const langMatch = className.match(/language-(\w+)/);
    const text =
      typeof codeEl.props?.children === 'string'
        ? codeEl.props.children
        : String(codeEl.props?.children ?? '');
    return { text: text.replace(/\n$/, ''), language: langMatch?.[1] };
  }

  return { text: String(children) };
}

export const CodeBlock = memo<{ children?: ReactNode }>(({ children, ...props }) => {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    return () => clearTimeout(timerRef.current);
  }, []);

  const { text, language } = extractCodeContent(children);

  // Mermaid diagrams get special rendering
  if (language === 'mermaid') {
    return <MermaidBlock chart={text} />;
  }

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      // silent fail
    }
  }, [text]);

  const handleOpenInCanvas = useCallback(() => {
    const id = `code-${Date.now()}`;
    const title = language ? `snippet.${language}` : 'snippet.txt';

    useCanvasStore.getState().openTab({
      id,
      title,
      type: 'code',
      content: text,
      language,
    });

    const currentMode = useLayoutModeStore.getState().mode;
    if (currentMode !== 'canvas') {
      useLayoutModeStore.getState().setMode('canvas');
    }
  }, [text, language]);

  // Short snippets (single line, < 80 chars) don't need action buttons
  const isShort = !text.includes('\n') && text.length < 80;

  return (
    <div className="group/code relative rounded-lg border border-slate-200 dark:border-slate-600 overflow-hidden">
      {/* Language label header */}
      {!isShort && language && (
        <div className="flex items-center justify-between px-3 py-1.5 bg-slate-200/80 dark:bg-slate-700/80">
          <span className="text-xs font-medium text-slate-500 dark:text-slate-400 select-none">
            {language}
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={handleOpenInCanvas}
              className="p-1 rounded hover:bg-slate-300/60 dark:hover:bg-slate-600/60 transition-colors text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
              title={t('agent.artifact.openInCanvas', 'Open in Canvas')}
            >
              <PanelRight size={14} />
            </button>
            <button
              type="button"
              onClick={handleCopy}
              className="p-1 rounded hover:bg-slate-300/60 dark:hover:bg-slate-600/60 transition-colors text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
              title={copied ? t('agent.actions.copied', 'Copied!') : t('agent.actions.copyCode', 'Copy code')}
            >
              {copied ? <Check size={14} className="text-emerald-500" /> : <Copy size={14} />}
            </button>
          </div>
        </div>
      )}
      <pre {...props} className="rounded-none! border-none!">
        {children}
      </pre>
      {!isShort && !language && (
        <div className="absolute top-2 right-2 flex items-center gap-1 opacity-0 group-hover/code:opacity-100 transition-opacity">
          <button
            type="button"
            onClick={handleOpenInCanvas}
            className="p-1 rounded bg-slate-700/80 hover:bg-slate-600 transition-colors text-slate-400 hover:text-slate-200"
            title={t('agent.artifact.openInCanvas', 'Open in Canvas')}
          >
            <PanelRight size={14} />
          </button>
          <button
            type="button"
            onClick={handleCopy}
            className="p-1 rounded bg-slate-700/80 hover:bg-slate-600 transition-colors text-slate-400 hover:text-slate-200"
            title={copied ? t('agent.actions.copied', 'Copied!') : t('agent.actions.copyCode', 'Copy code')}
          >
            {copied ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
          </button>
        </div>
      )}
    </div>
  );
});

CodeBlock.displayName = 'CodeBlock';
