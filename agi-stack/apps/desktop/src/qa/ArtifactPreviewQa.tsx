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
  content?: string;
  source?: 'pdf' | 'docx' | 'xlsx' | 'audio' | 'video' | 'png';
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
    title: 'evidence.png',
    mimeType: 'image/png',
    source: 'png',
  },
  {
    id: 'pdf',
    label: 'PDF',
    title: 'desktop-client-prd.pdf',
    mimeType: 'application/pdf',
    source: 'pdf',
  },
  {
    id: 'docx',
    label: 'DOCX',
    title: 'desktop-client-prd.docx',
    mimeType:
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    source: 'docx',
  },
  {
    id: 'xlsx',
    label: 'XLSX',
    title: 'parity-matrix.xlsx',
    mimeType:
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    source: 'xlsx',
  },
  {
    id: 'audio',
    label: 'Audio',
    title: 'notification.wav',
    mimeType: 'audio/wav',
    source: 'audio',
  },
  {
    id: 'video',
    label: 'Video',
    title: 'runtime-preview.webm',
    mimeType: 'video/webm',
    source: 'video',
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
        return loadPreviewFixture(selected);
      },
    }),
    [selected],
  );

  return (
    <Theme accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <main className="parity-runtime-qa">
        <header data-qa-format={selected.id}>
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
                data-qa-format={fixture.id}
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
              sizeBytes={
                selected.content
                  ? new TextEncoder().encode(selected.content).byteLength
                  : 1
              }
              title={selected.title}
            />
          </section>
        </div>
      </main>
    </Theme>
  );
}

async function loadPreviewFixture(fixture: PreviewFixture): Promise<Blob> {
  if (fixture.source === 'pdf' || fixture.source === 'docx') {
    const extension = fixture.source;
    const response = await fetch(
      `/docs/product/desktop-agent-ui/MemStack-Desktop-Agent-Client-PRD.${extension}`,
    );
    if (!response.ok) throw new Error('artifact_preview_fixture_unavailable');
    return new Blob([await response.arrayBuffer()], { type: fixture.mimeType });
  }
  if (fixture.source === 'xlsx') {
    const XLSX = await import('xlsx');
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(
      workbook,
      XLSX.utils.aoa_to_sheet([
        ['Surface', 'Authority', 'Status'],
        ['Terminal', 'cloud', 'ready'],
        ['Workspace', 'cloud', 'ready'],
        ['Artifact', 'cloud', 'ready'],
      ]),
      'Parity',
    );
    return new Blob(
      [
        XLSX.write(workbook, {
          type: 'array',
          bookType: 'xlsx',
          compression: true,
        }),
      ],
      { type: fixture.mimeType },
    );
  }
  if (fixture.source === 'audio') {
    return new Blob([silentWav()], { type: fixture.mimeType });
  }
  if (fixture.source === 'video') {
    return new Blob([new Uint8Array([0x1a, 0x45, 0xdf, 0xa3])], {
      type: fixture.mimeType,
    });
  }
  if (fixture.source === 'png') {
    return new Blob(
      [
        decodeBase64(
          'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
        ),
      ],
      { type: fixture.mimeType },
    );
  }
  return new Blob([fixture.content ?? ''], { type: fixture.mimeType });
}

function decodeBase64(value: string): ArrayBuffer {
  const decoded = atob(value);
  const bytes = new Uint8Array(new ArrayBuffer(decoded.length));
  for (let index = 0; index < decoded.length; index += 1) {
    bytes[index] = decoded.charCodeAt(index);
  }
  return bytes.buffer;
}

function silentWav(): ArrayBuffer {
  const sampleRate = 8_000;
  const samples = 800;
  const buffer = new ArrayBuffer(44 + samples * 2);
  const view = new DataView(buffer);
  const writeAscii = (offset: number, value: string) => {
    for (let index = 0; index < value.length; index += 1) {
      view.setUint8(offset + index, value.charCodeAt(index));
    }
  };
  writeAscii(0, 'RIFF');
  view.setUint32(4, buffer.byteLength - 8, true);
  writeAscii(8, 'WAVE');
  writeAscii(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(36, 'data');
  view.setUint32(40, samples * 2, true);
  return buffer;
}

const container = document.getElementById('root');
if (!container) throw new Error('Missing root element');
globalThis.__artifactPreviewQaRoot ??= createRoot(container);
globalThis.__artifactPreviewQaRoot.render(
  <I18nProvider>
    <ArtifactPreviewQa />
  </I18nProvider>,
);
