import '@radix-ui/themes/styles.css';
import { Theme } from '@radix-ui/themes';
import { useMemo, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { ArtifactPreviewSurface } from '../features/chat/ArtifactPreviewSurface';
import type { DesktopArtifactClient } from '../features/chat/desktopArtifactClient';
import { I18nProvider } from '../i18n';
import '../styles.css';
import './parityRuntimeQa.css';

declare global {
  var __artifactPreviewQaRoot: Root | undefined;
}

type PreviewFixture = {
  id: string;
  label: string;
  title: string;
  mimeType: string;
  content: string;
};

const fixtures: readonly PreviewFixture[] = [
  {
    id: 'html',
    label: 'HTML',
    title: 'security-report.html',
    mimeType: 'text/html',
    content:
      '<main><h1>Sanitized report</h1><p>Scripts, forms, and navigation are removed.</p><script>throw new Error("unsafe")</script></main>',
  },
  {
    id: 'svg',
    label: 'SVG',
    title: 'topology.svg',
    mimeType: 'image/svg+xml',
    content:
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 280"><rect width="640" height="280" fill="#0b1018"/><circle cx="160" cy="140" r="52" fill="#12b8ff"/><circle cx="480" cy="140" r="52" fill="#66d99f"/><path d="M220 140h200" stroke="#d6e2f0" stroke-width="8"/><text x="115" y="225" fill="#fff">Desktop</text><text x="445" y="225" fill="#fff">Cloud</text></svg>',
  },
  {
    id: 'image',
    label: 'Image',
    title: 'evidence.svg',
    mimeType: 'image/svg+xml',
    content:
      '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="420"><rect width="800" height="420" fill="#132235"/><text x="48" y="100" fill="#fff" font-size="36">Immutable release evidence</text><text x="48" y="160" fill="#8ccfff" font-size="24">Tag CI pending</text></svg>',
  },
  {
    id: 'legacy-office',
    label: 'Legacy Office',
    title: 'migration-plan.ppt',
    mimeType: 'application/vnd.ms-powerpoint',
    content: 'legacy-office-download-fallback',
  },
];

function ArtifactPreviewQa() {
  const [selectedId, setSelectedId] = useState(fixtures[0].id);
  const selected = fixtures.find(({ id }) => id === selectedId) ?? fixtures[0];
  const client = useMemo<DesktopArtifactClient>(
    () => ({
      async loadContent() {
        throw new Error('artifact_content_not_used_by_preview_fixture');
      },
      async saveContent() {
        throw new Error('artifact_save_not_used_by_preview_fixture');
      },
      async download() {
        return new Blob([selected.content], { type: selected.mimeType });
      },
    }),
    [selected],
  );

  return (
    <Theme accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <main className="parity-runtime-qa">
        <header>
          <div>
            <h1>Artifact Preview</h1>
            <p>
              Authenticated bytes become controlled Blob URLs; unsafe and unsupported formats
              fail closed to download.
            </p>
          </div>
        </header>
        <div className="parity-runtime-qa__surface">
          <nav className="parity-runtime-qa__preview-nav" aria-label="Artifact preview formats">
            {fixtures.map((fixture) => (
              <button
                key={fixture.id}
                type="button"
                aria-pressed={selected.id === fixture.id}
                onClick={() => setSelectedId(fixture.id)}
              >
                {fixture.label}
              </button>
            ))}
          </nav>
          <section className="parity-runtime-qa__preview">
            <ArtifactPreviewSurface
              key={selected.id}
              artifactId={`artifact-${selected.id}`}
              client={client}
              mimeType={selected.mimeType}
              sizeBytes={new TextEncoder().encode(selected.content).byteLength}
              title={selected.title}
            />
          </section>
        </div>
      </main>
    </Theme>
  );
}

const container = document.getElementById('root');
if (!container) throw new Error('Missing root element');
globalThis.__artifactPreviewQaRoot ??= createRoot(container);
globalThis.__artifactPreviewQaRoot.render(
  <I18nProvider>
    <ArtifactPreviewQa />
  </I18nProvider>,
);
