import { useState, useEffect } from 'react';
import type { SyntaxHighlighterBundle } from '@business/agent/ui/web/chat/syntaxHighlighterTypes';
export type { SyntaxHighlighterBundle } from '@business/agent/ui/web/chat/syntaxHighlighterTypes';

// Lazy-loaded syntax highlighter singleton (hljs — more reliable than Prism with Vite)
let _SyntaxHighlighter: SyntaxHighlighterBundle['SyntaxHighlighter'] | null = null;
let _theme: SyntaxHighlighterBundle['theme'] | null = null;
let _loadingPromise: Promise<void> | null = null;

export function loadHighlighter(): Promise<void> {
  if (_SyntaxHighlighter && _theme) return Promise.resolve();
  if (_loadingPromise) return _loadingPromise;
  _loadingPromise = Promise.all([
    import('react-syntax-highlighter/dist/esm/light-async'),
    import('react-syntax-highlighter/dist/esm/styles/hljs/vs2015'),
  ])
    .then(([mod, { default: vs2015 }]) => {
      _SyntaxHighlighter = mod.default as SyntaxHighlighterBundle['SyntaxHighlighter'];
      _theme = vs2015 as SyntaxHighlighterBundle['theme'];
    })
    .catch(() => {
      _loadingPromise = null;
    });
  return _loadingPromise;
}

export function useSyntaxHighlighter(): SyntaxHighlighterBundle | null {
  const [ready, setReady] = useState(_SyntaxHighlighter !== null);

  useEffect(() => {
    if (ready) return;
    void loadHighlighter().then(() => {
      if (_SyntaxHighlighter && _theme) setReady(true);
    });
  }, [ready]);

  if (!ready || !_SyntaxHighlighter || !_theme) return null;
  return { SyntaxHighlighter: _SyntaxHighlighter, theme: _theme };
}
