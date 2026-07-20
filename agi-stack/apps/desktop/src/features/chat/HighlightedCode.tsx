import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { CheckIcon, CopyIcon } from '@radix-ui/react-icons';
import hljs from 'highlight.js/lib/common';

import { useI18n } from '../../i18n';

// highlight.js token colors are themed in styles.css (`.hljs-*`) so code in
// chat matches the desktop dark palette instead of a stock theme.

const LANGUAGE_ALIASES: Record<string, string> = {
  ts: 'typescript',
  tsx: 'typescript',
  js: 'javascript',
  jsx: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  py: 'python',
  rs: 'rust',
  sh: 'bash',
  shell: 'bash',
  zsh: 'bash',
  yml: 'yaml',
  md: 'markdown',
  'c++': 'cpp',
  'objective-c': 'objectivec',
  gql: 'graphql',
  plaintext: 'plaintext',
  text: 'plaintext',
  txt: 'plaintext',
};

export function resolveHighlightLanguage(language: string | undefined | null): string {
  if (!language) return 'plaintext';
  const normalized = language.trim().toLowerCase();
  const aliased = LANGUAGE_ALIASES[normalized] ?? normalized;
  return hljs.getLanguage(aliased) ? aliased : 'plaintext';
}

export function highlightCodeToHtml(code: string, language: string | undefined | null): string {
  try {
    return hljs.highlight(code, { language: resolveHighlightLanguage(language) }).value;
  } catch {
    return escapeHtml(code);
  }
}

/**
 * Framed code block with a header (language label + copy button), syntax
 * highlighting, and an optional "show all N lines" clamp for long outputs.
 * Copy always uses the raw source string so soft-wrapping never leaks
 * display line breaks into the clipboard.
 */
export const CodeBlockFrame = memo(function CodeBlockFrame({
  code,
  language,
  collapsibleAfterLines,
  wrap = false,
  className,
}: {
  code: string;
  language: string;
  collapsibleAfterLines?: number;
  /** Soft-wrap long lines instead of horizontal scrolling (tool payloads). */
  wrap?: boolean;
  className?: string;
}) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const copyResetRef = useRef<number | null>(null);
  const resolvedLanguage = resolveHighlightLanguage(language);
  const highlightedHtml = useMemo(
    () => highlightCodeToHtml(code, resolvedLanguage),
    [code, resolvedLanguage],
  );
  const lineCount = useMemo(() => countLines(code), [code]);
  const collapsible =
    typeof collapsibleAfterLines === 'number' && lineCount > collapsibleAfterLines;
  const collapsed = collapsible && !expanded;

  useEffect(() => {
    return () => {
      if (copyResetRef.current !== null) window.clearTimeout(copyResetRef.current);
    };
  }, []);

  const copyCode = () => {
    if (navigator.clipboard) void navigator.clipboard.writeText(code);
    setCopied(true);
    if (copyResetRef.current !== null) window.clearTimeout(copyResetRef.current);
    copyResetRef.current = window.setTimeout(() => setCopied(false), 1400);
  };

  return (
    <div
      className={`code-block-frame${collapsed ? ' is-collapsed' : ''}${wrap ? ' is-wrapped' : ''}${
        className ? ` ${className}` : ''
      }`}
    >
      <div className="code-block-head">
        <span className="code-block-lang">{resolvedLanguage}</span>
        <button
          type="button"
          className="code-block-copy"
          aria-label={t('chat.copyCode')}
          onClick={copyCode}
        >
          {copied ? <CheckIcon aria-hidden="true" /> : <CopyIcon aria-hidden="true" />}
          <span>{copied ? t('chat.copied') : t('chat.copyCode')}</span>
        </button>
      </div>
      <pre className="code-block-body">
        <code
          className={`hljs language-${resolvedLanguage}`}
          dangerouslySetInnerHTML={{ __html: highlightedHtml }}
        />
      </pre>
      {collapsed ? <span className="code-block-fade" aria-hidden="true" /> : null}
      {collapsible ? (
        <button
          type="button"
          className="code-block-toggle"
          aria-expanded={expanded}
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded
            ? t('chat.collapseOutput')
            : t('chat.showFullOutput', { count: lineCount })}
        </button>
      ) : null}
    </div>
  );
});

function countLines(code: string): number {
  if (!code) return 0;
  let count = 1;
  for (let index = 0; index < code.length; index += 1) {
    if (code[index] === '\n') count += 1;
  }
  return count;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
