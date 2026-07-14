import '@radix-ui/themes/styles.css';
import { Badge, Heading, Theme } from '@radix-ui/themes';
import React from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { SessionEvidenceCanvas } from '../features/session/SessionEvidenceCanvas';
import { I18nProvider } from '../i18n';
import type { DesktopArtifactVersion } from '../types';
import '../styles.css';
import './sessionEvidenceQa.css';

declare global {
  var __sessionEvidenceQaRoot: Root | undefined;
}

const versions: DesktopArtifactVersion[] = [
  {
    id: 'artifact-version-brief-v1',
    artifact_id: 'artifact-brief',
    source_artifact_id: 'source-artifact-brief',
    conversation_id: 'conversation-evidence-qa',
    run_id: 'run-042',
    version: 1,
    status: 'superseded',
    revision: 1,
    filename: 'agent-desktop-brief.md',
    mime_type: 'text/markdown',
    path: '/workspace/docs/agent-desktop-brief.md',
    relative_path: 'docs/agent-desktop-brief.md',
    bytes: 6842,
    sources: [{ id: 'obsolete-source', label: 'Superseded source' }],
    checks: [{ id: 'obsolete-check', label: 'Superseded check', status: 'failed' }],
    created_at: '2026-07-13T08:00:00Z',
    updated_at: '2026-07-13T08:00:00Z',
    superseded_at: '2026-07-13T08:34:00Z',
  },
  {
    id: 'artifact-version-brief-v2',
    artifact_id: 'artifact-brief',
    source_artifact_id: 'source-artifact-brief',
    conversation_id: 'conversation-evidence-qa',
    run_id: 'run-042',
    version: 2,
    status: 'ready',
    revision: 7,
    filename: 'agent-desktop-brief.md',
    mime_type: 'text/markdown',
    path: '/workspace/docs/agent-desktop-brief.md',
    relative_path: 'docs/agent-desktop-brief.md',
    bytes: 9120,
    sources: [
      {
        id: 'source-codex-app',
        kind: 'product-reference',
        label: 'Codex App session interaction reference',
        uri: 'https://openai.com/codex/',
        status: 'verified',
      },
      {
        id: 'source-runtime-contract',
        kind: 'repository-file',
        label: 'Desktop runtime contract',
        path: 'agi-stack/apps/desktop/src-tauri/src/server/mod.rs',
        line: 214,
        status: 'verified',
      },
    ],
    checks: [
      {
        id: 'check-session-model',
        kind: 'unit-test',
        label: 'Session evidence model tests',
        path: 'tests/session-evidence-model.test.mjs',
        status: 'passed',
      },
      {
        id: 'check-web-build',
        kind: 'build',
        label: 'Desktop TypeScript and Vite build',
        status: 'passed',
      },
      {
        id: 'check-provider-contract',
        kind: 'integration-test',
        label: 'Provider authorization contract',
        status: 'blocked',
      },
    ],
    created_at: '2026-07-13T08:34:00Z',
    updated_at: '2026-07-13T09:12:00Z',
  },
  {
    id: 'artifact-version-export-v1',
    artifact_id: 'artifact-export',
    source_artifact_id: 'source-artifact-export',
    conversation_id: 'conversation-evidence-qa',
    run_id: 'run-042',
    version: 1,
    status: 'draft',
    revision: 2,
    filename: 'workspace-research-export.pdf',
    mime_type: 'application/pdf',
    path: '/workspace/exports/workspace-research-export.pdf',
    relative_path: 'exports/workspace-research-export.pdf',
    bytes: 182044,
    sources: [],
    checks: [],
    created_at: '2026-07-13T09:06:00Z',
    updated_at: '2026-07-13T09:06:00Z',
  },
];

function SessionEvidenceQa() {
  const params = new URLSearchParams(window.location.search);
  const checksView = params.get('view') === 'checks';
  const presentation = checksView ? 'checks' : 'sources';

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <main className="qa-evidence-page">
        <aside className="review-panel review-panel-stage qa-evidence-panel">
          <header className="review-head">
            <div>
              <Heading as="h2" size="3">
                Agent desktop session design
              </Heading>
              <span>Session / run-042 / revision 7</span>
            </div>
            <Badge color="green" variant="soft">
              ready
            </Badge>
          </header>
          <div className="review-tabs" aria-label="Workspace tabs">
            <nav className="review-tab-scroll">
              <button className="review-tab" type="button">
                <span>Overview</span>
              </button>
              <button className="review-tab" type="button">
                <span>Artifacts</span>
                <em>2</em>
              </button>
              <button className={`review-tab ${checksView ? '' : 'selected'}`} type="button">
                <span>Sources</span>
                <em>2</em>
              </button>
              <button className={`review-tab ${checksView ? 'selected' : ''}`} type="button">
                <span>Checks</span>
                <em>3</em>
              </button>
            </nav>
          </div>
          <div className="review-content">
            <SessionEvidenceCanvas
              collection={checksView ? 'checks' : 'sources'}
              presentation={presentation}
              versions={versions}
              available
              onOpenArtifact={() => undefined}
            />
          </div>
        </aside>
      </main>
    </Theme>
  );
}

const root = document.getElementById('root');
if (!root) throw new Error('Missing #root container');

const qaRoot = globalThis.__sessionEvidenceQaRoot ?? createRoot(root);
globalThis.__sessionEvidenceQaRoot = qaRoot;

qaRoot.render(
  <React.StrictMode>
    <I18nProvider>
      <SessionEvidenceQa />
    </I18nProvider>
  </React.StrictMode>,
);
