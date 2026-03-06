import { useState, useEffect } from 'react';

// Lazy-loaded syntax highlighter singleton (hljs — more reliable than Prism with Vite)
let _SyntaxHighlighter: any = null;
let _theme: any = null;
let _loadingPromise: Promise<void> | null = null;

export function loadHighlighter(): Promise<void> {
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

export function useSyntaxHighlighter() {
  const [ready, setReady] = useState(_SyntaxHighlighter !== null);

  useEffect(() => {
    if (ready) return;
    loadHighlighter().then(() => {
      if (_SyntaxHighlighter) setReady(true);
    });
  }, [ready]);

  return ready ? { SyntaxHighlighter: _SyntaxHighlighter, theme: _theme } : null;
}
