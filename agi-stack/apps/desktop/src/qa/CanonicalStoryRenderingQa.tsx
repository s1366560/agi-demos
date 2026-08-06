import '@radix-ui/themes/styles.css';
import { useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Button, Theme } from '@radix-ui/themes';

import { MarkdownContent } from '../features/chat/ChatTranscript';
import { I18nProvider } from '../i18n';
import { ToastProvider } from '../features/feedback/ToastCenter';
import '../styles/global.css';
import '../features/chat/ChatPanel.css';

declare global {
  var __canonicalStoryRenderingQaRoot: Root | undefined;
}

type QaAppearance = 'dark' | 'light';
type QaScenario = 'valid' | 'invalid' | 'ordinary';

const VALID_STORY = [
  '```canonical-story',
  'story:',
  '  version: 1',
  '  language: zh-CN',
  '  title: Safe <script>alert(1)</script> title with a long review label',
  '  problem_statement: Desktop should render structured stories as inspectable cards.',
  '  user_value: Reviewers can scan acceptance and dependency state.',
  '  acceptance_criteria:',
  '    - id: AC-1',
  '      text: The story renders as one accessible card.',
  '      testable: true',
  '    - id: AC-2',
  '      text: Expanded details wrap without horizontal overflow.',
  '      testable: true',
  '  constraints_and_affected_areas:',
  '    - Desktop transcript',
  '    - Browser and Electron verification',
  '  dependencies_and_sequencing:',
  '    independent_story_check: fail',
  '    depends_on:',
  '      - Renderer contract review',
  '    unblock_condition: Schema and accessibility tests pass.',
  '  out_of_scope:',
  '    - Canvas lifecycle',
  '  invest:',
  '    independent: { status: warning, reason: One renderer dependency remains. }',
  '    negotiable: { status: pass, reason: Presentation may evolve. }',
  '    valuable: { status: pass, reason: Improves reviewability. }',
  '    estimable: { status: pass, reason: Bounded component. }',
  '    small: { status: pass, reason: Single shared renderer. }',
  '    testable: { status: pass, reason: Schema and DOM are deterministic. }',
  '```',
].join('\n');

const INVALID_STORY = [
  '```canonical-story',
  'story:',
  '  version: invalid',
  '  title: Missing required fields',
  '```',
].join('\n');

const ORDINARY_YAML = [
  '```yaml',
  'story: this is ordinary application configuration',
  'status: ready',
  'items:',
  '  - one',
  '  - two',
  '```',
].join('\n');

const CONTENT: Record<QaScenario, string> = {
  valid: VALID_STORY,
  invalid: INVALID_STORY,
  ordinary: ORDINARY_YAML,
};

function CanonicalStoryRenderingQa() {
  const [scenario, setScenario] = useState<QaScenario>('valid');
  const [appearance, setAppearance] = useState<QaAppearance>('dark');
  const [narrow, setNarrow] = useState(false);

  return (
    <Theme appearance={appearance} accentColor="cyan" grayColor="slate" radius="medium">
      <main className="session-workspace-thread" style={{ minHeight: '100vh', padding: 24 }}>
        <section
          className="pane-shell chat-shell session-chat-narrative"
          data-testid="canonical-story-qa-shell"
          style={{
            width: narrow ? 360 : undefined,
            maxWidth: narrow ? 360 : 900,
            minHeight: 620,
            margin: '0 auto',
          }}
        >
          <header style={{ display: 'flex', flexWrap: 'wrap', gap: 10, padding: 16 }}>
            <Button type="button" onClick={() => setScenario('valid')}>
              Valid story
            </Button>
            <Button type="button" onClick={() => setScenario('invalid')}>
              Invalid explicit
            </Button>
            <Button type="button" onClick={() => setScenario('ordinary')}>
              Ordinary YAML
            </Button>
            <Button
              type="button"
              onClick={() => setAppearance((current) => (current === 'dark' ? 'light' : 'dark'))}
            >
              Toggle theme
            </Button>
            <Button type="button" onClick={() => setNarrow((current) => !current)}>
              Toggle narrow
            </Button>
            <span data-testid="canonical-story-qa-scenario">{scenario}</span>
            <span data-testid="canonical-story-qa-appearance">{appearance}</span>
            <span data-testid="canonical-story-qa-width">{narrow ? 'narrow' : 'wide'}</span>
          </header>
          <div className="message-scroll">
            <div className="message-stack">
              <article className="message session-thread-message agent">
                <div className="session-message-body">
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
  if (!globalThis.__canonicalStoryRenderingQaRoot) {
    globalThis.__canonicalStoryRenderingQaRoot = createRoot(container);
  }
  globalThis.__canonicalStoryRenderingQaRoot.render(
    <I18nProvider>
      <ToastProvider>
        <CanonicalStoryRenderingQa />
      </ToastProvider>
    </I18nProvider>,
  );
}

mount();
