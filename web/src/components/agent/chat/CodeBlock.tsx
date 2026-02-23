/**
 * CodeBlock - Custom code block renderer for ReactMarkdown
 *
 * Adds syntax highlighting (lazy-loaded hljs), language label header,
 * copy/canvas action buttons, and mermaid diagram rendering.
 * Used as a `components.pre` override in ReactMarkdown instances.
 */

import { memo, useState, useCallback, useRef, useEffect } from 'react';
import type { ReactElement, ReactNode, HTMLAttributes } from 'react';

import { useTranslation } from 'react-i18next';

import { Copy, Check, PanelRight } from 'lucide-react';

import { useCanvasStore } from '@/stores/canvasStore';
import { useLayoutModeStore } from '@/stores/layoutMode';

import { MermaidBlock } from './MermaidBlock';

function extractCodeContent(children: ReactNode): { text: string; language?: string } {
  if (!children) return { text: '' };

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

// Lazy-loaded syntax highlighter singleton (hljs — more reliable than Prism with Vite)
let _SyntaxHighlighter: any = null;
let _theme: any = null;
let _loadingPromise: Promise<void> | null = null;

function loadHighlighter(): Promise<void> {
  if (_SyntaxHighlighter && _theme) return Promise.resolve();
  if (_loadingPromise) return _loadingPromise;
  _loadingPromise = Promise.all([
    import('react-syntax-highlighter'),
    import('react-syntax-highlighter/dist/esm/styles/hljs'),
  ])
    .then(([mod, { vs2015 }]) => {
      _SyntaxHighlighter = mod.default;
      _theme = vs2015;
    })
    .catch(() => {
      _loadingPromise = null;
    });
  return _loadingPromise;
}

function useSyntaxHighlighter() {
  const [ready, setReady] = useState(_SyntaxHighlighter !== null);

  useEffect(() => {
    if (ready) return;
    loadHighlighter().then(() => {
      if (_SyntaxHighlighter) setReady(true);
    });
  }, [ready]);

  return ready ? { SyntaxHighlighter: _SyntaxHighlighter, theme: _theme } : null;
}

export const CodeBlock = memo<{ children?: ReactNode }>(({ children, ...props }) => {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const highlighter = useSyntaxHighlighter();

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
              title={
                copied
                  ? t('agent.actions.copied', 'Copied!')
                  : t('agent.actions.copyCode', 'Copy code')
              }
            >
              {copied ? <Check size={14} className="text-emerald-500" /> : <Copy size={14} />}
            </button>
          </div>
        </div>
      )}

      {/* Code content — highlighted or plain */}
      {highlighter && language ? (
        <div className="syntax-highlighted">
          <highlighter.SyntaxHighlighter
            style={highlighter.theme}
            language={language}
            PreTag="div"
            customStyle={{ margin: 0, borderRadius: 0, fontSize: '0.8125rem', lineHeight: 1.6 }}
          >
            {text}
          </highlighter.SyntaxHighlighter>
        </div>
      ) : (
        <pre {...props} className="rounded-none! border-none!">
          {children}
        </pre>
      )}

      {/* Hover actions for blocks without language header */}
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
            title={
              copied
                ? t('agent.actions.copied', 'Copied!')
                : t('agent.actions.copyCode', 'Copy code')
            }
          >
            {copied ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
          </button>
        </div>
      )}
    </div>
  );
});

CodeBlock.displayName = 'CodeBlock';
