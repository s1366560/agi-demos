import '@radix-ui/themes/styles.css';
import React, { useMemo, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Button, Theme } from '@radix-ui/themes';

import { MarkdownContent } from '../features/chat/ChatTranscript';
import { sanitizeMermaidSvg } from '../features/chat/mermaidSvgSanitizer';
import { I18nProvider } from '../i18n';
import '../styles.css';
import '../features/chat/ChatPanel.css';

declare global {
  var __mermaidRenderingQaRoot: Root | undefined;
}

type QaScenario = 'valid' | 'invalid' | 'malicious' | 'ordinary';
type QaAppearance = 'dark' | 'light';

const CONTENT: Record<QaScenario, string> = {
  valid: [
    'The request path is:',
    '',
    '```mermaid',
    'flowchart LR',
    '  A[Request] --> B{Safe?}',
    '  B -->|Yes| C[Render]',
    '  B -->|No| D[Reject]',
    '```',
  ].join('\n'),
  invalid: [
    'This source must fall back safely:',
    '',
    '```mermaid',
    'flowchart LR',
    '  A[Unclosed node --> B',
    '```',
  ].join('\n'),
  malicious: [
    'Strict mode must reject executable links:',
    '',
    '```mermaid',
    'flowchart LR',
    '  A[Untrusted] --> B[Sanitized]',
    '  click A "javascript:alert(1)" "Danger"',
    '```',
  ].join('\n'),
  ordinary: [
    'Only the Mermaid fence receives diagram rendering:',
    '',
    '```typescript',
    'const diagram = "ordinary code";',
    '```',
    '',
    'Inline `mermaid` stays inline.',
  ].join('\n'),
};

const MALICIOUS_SVG_PROBE = [
  '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">',
  '<script>alert(1)</script>',
  '<foreignObject><iframe src="https://example.com"></iframe></foreignObject>',
  '<a href="javascript:alert(1)"><text>unsafe</text></a>',
  '<path id="safe-path" d="M0 0 L10 10" stroke="currentColor" />',
  '</svg>',
].join('');

function installQaClipboard() {
  const writeText = async (value: string) => {
    document.body.setAttribute('data-mermaid-copied', value);
  };
  try {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
  } catch {
    Object.defineProperty(navigator.clipboard, 'writeText', {
      configurable: true,
      value: writeText,
    });
  }
}

function MermaidRenderingQa() {
  const [scenario, setScenario] = useState<QaScenario>('valid');
  const [appearance, setAppearance] = useState<QaAppearance>('dark');
  const [narrow, setNarrow] = useState(false);
  const sanitizedProbe = useMemo(() => sanitizeMermaidSvg(MALICIOUS_SVG_PROBE), []);
  const sanitizerSafe =
    sanitizedProbe.includes('safe-path') &&
    !/(?:<script|foreignObject|iframe|onload|javascript:)/i.test(sanitizedProbe);

  return (
    <Theme appearance={appearance} accentColor="cyan" grayColor="slate" radius="medium">
      <main
        className="session-workspace-thread"
        style={{ minHeight: '100vh', padding: 24 }}
      >
        <section
          className="pane-shell chat-shell session-chat-narrative"
          style={{
            width: narrow ? 360 : undefined,
            maxWidth: narrow ? 360 : 900,
            minHeight: 640,
            margin: '0 auto',
          }}
        >
          <header style={{ display: 'flex', flexWrap: 'wrap', gap: 10, padding: 16 }}>
            <Button type="button" onClick={() => setScenario('valid')}>
              Valid diagram
            </Button>
            <Button type="button" onClick={() => setScenario('invalid')}>
              Invalid diagram
            </Button>
            <Button type="button" onClick={() => setScenario('malicious')}>
              Malicious diagram
            </Button>
            <Button type="button" onClick={() => setScenario('ordinary')}>
              Ordinary code
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
            <span data-testid="mermaid-qa-scenario">{scenario}</span>
            <span data-testid="mermaid-qa-appearance">{appearance}</span>
            <span data-testid="mermaid-qa-width">{narrow ? 'narrow' : 'wide'}</span>
            <span data-testid="mermaid-sanitizer-result">
              {sanitizerSafe ? 'safe' : 'unsafe'}
            </span>
          </header>
          <div className="message-scroll">
            <div className="message-stack">
              <article className="message session-thread-message agent">
                <div className="session-message-body" data-testid="mermaid-markdown">
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
  installQaClipboard();
  if (!globalThis.__mermaidRenderingQaRoot) {
    globalThis.__mermaidRenderingQaRoot = createRoot(container);
  }
  globalThis.__mermaidRenderingQaRoot.render(
    <React.StrictMode>
      <I18nProvider>
        <MermaidRenderingQa />
      </I18nProvider>
    </React.StrictMode>,
  );
}

mount();
