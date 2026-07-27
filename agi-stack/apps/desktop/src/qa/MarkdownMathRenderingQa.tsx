import '@radix-ui/themes/styles.css';
import React, { useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Button, Theme } from '@radix-ui/themes';

import { MarkdownContent } from '../features/chat/ChatTranscript';
import { I18nProvider } from '../i18n';
import { ToastProvider } from '../features/feedback/ToastCenter';
import '../styles.css';
import '../features/chat/ChatPanel.css';

declare global {
  var __markdownMathRenderingQaRoot: Root | undefined;
}

type QaScenario = 'plain' | 'valid' | 'incomplete' | 'code' | 'links';
type QaAppearance = 'dark' | 'light';

const LONG_DISPLAY_MATH = [
  '\\displaystyle f(x_1,\\ldots,x_{12}) =',
  '\\alpha_1x_1 + \\alpha_2x_2 + \\alpha_3x_3 + \\alpha_4x_4',
  '+ \\alpha_5x_5 + \\alpha_6x_6 + \\alpha_7x_7 + \\alpha_8x_8',
  '+ \\alpha_9x_9 + \\alpha_{10}x_{10} + \\alpha_{11}x_{11} + \\alpha_{12}x_{12}',
].join(' ');

const CONTENT: Record<QaScenario, string> = {
  plain: [
    'Ordinary Markdown stays lightweight.',
    '',
    '| Feature | State |',
    '| --- | --- |',
    '| GFM table | ready |',
  ].join('\n'),
  valid: [
    'Inline energy is $E=mc^2$ within the sentence.',
    '',
    '$$',
    LONG_DISPLAY_MATH,
    '$$',
  ].join('\n'),
  incomplete: 'A streaming fragment remains readable: $E=mc',
  code: [
    'Inline code remains literal: `$x$`.',
    '',
    '```typescript',
    'const price = "$5";',
    '```',
  ].join('\n'),
  links: [
    '[HTTPS documentation](https://docs.example.test/guide#usage)',
    '',
    '[Loopback HTTP](http://127.0.0.1:5173/qa/markdown-math-rendering.html)',
    '',
    '[Restricted HTTP](http://docs.example.test/guide)',
    '',
    '[Relative route](/relative/path)',
    '',
    '[Unsafe protocol](javascript:alert(1))',
    '',
    '[Formatted **documentation**](https://docs.example.test/nested)',
  ].join('\n'),
};

function MarkdownMathRenderingQa() {
  const [scenario, setScenario] = useState<QaScenario>('plain');
  const [appearance, setAppearance] = useState<QaAppearance>('dark');
  const [narrow, setNarrow] = useState(false);

  return (
    <Theme appearance={appearance} accentColor="cyan" grayColor="slate" radius="medium">
      <main className="session-workspace-thread" style={{ minHeight: '100vh', padding: 24 }}>
        <section
          className="pane-shell chat-shell session-chat-narrative"
          data-testid="math-qa-shell"
          style={{
            width: narrow ? 360 : undefined,
            maxWidth: narrow ? 360 : 900,
            minHeight: 560,
            margin: '0 auto',
          }}
        >
          <header style={{ display: 'flex', flexWrap: 'wrap', gap: 10, padding: 16 }}>
            <Button type="button" onClick={() => setScenario('plain')}>
              Plain Markdown
            </Button>
            <Button type="button" onClick={() => setScenario('valid')}>
              Valid math
            </Button>
            <Button type="button" onClick={() => setScenario('incomplete')}>
              Incomplete math
            </Button>
            <Button type="button" onClick={() => setScenario('code')}>
              Code dollar
            </Button>
            <Button type="button" onClick={() => setScenario('links')}>
              Links
            </Button>
            <Button
              type="button"
              onClick={() =>
                setAppearance((current) => (current === 'dark' ? 'light' : 'dark'))
              }
            >
              Toggle theme
            </Button>
            <Button type="button" onClick={() => setNarrow((current) => !current)}>
              Toggle narrow
            </Button>
            <span data-testid="math-qa-scenario">{scenario}</span>
            <span data-testid="math-qa-appearance">{appearance}</span>
            <span data-testid="math-qa-width">{narrow ? 'narrow' : 'wide'}</span>
          </header>
          <div className="message-scroll">
            <div className="message-stack">
              <article className="message session-thread-message agent">
                <div className="session-message-body" data-testid="math-markdown">
                  <MarkdownContent
                    content={CONTENT[scenario]}
                    className="transcript-content"
                  />
                </div>
              </article>
            </div>
          </div>
        </section>
      </main>
    </Theme>
  );
}

function mount() {
  const container = document.getElementById('root');
  if (!container) return;
  if (!globalThis.__markdownMathRenderingQaRoot) {
    globalThis.__markdownMathRenderingQaRoot = createRoot(container);
  }
  globalThis.__markdownMathRenderingQaRoot.render(
    <React.StrictMode>
      <I18nProvider>
        <ToastProvider>
          <MarkdownMathRenderingQa />
        </ToastProvider>
      </I18nProvider>
    </React.StrictMode>,
  );
}

mount();
