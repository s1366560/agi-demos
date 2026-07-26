import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  assistantArtifactReferences,
  formatAssistantArtifactSize,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/assistantArtifactReferenceModel.js',
);

const readSource = (path) =>
  readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
const readOptionalSource = (path) => {
  const url = new URL(`../src/${path}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
};

const componentSource = readOptionalSource(
  'features/chat/AssistantArtifactReferences.tsx',
);
const timelineSource = readSource('features/chat/ChatTimeline.tsx');
const transcriptSource = readSource('features/chat/ChatTranscript.tsx');
const stylesSource = readSource('features/chat/ChatPanel.css');
const qaSource = readOptionalSource('qa/AssistantArtifactReferencesQa.tsx');

test('assistant artifact references normalize safe structured fields', () => {
  assert.deepEqual(
    assistantArtifactReferences({
      artifacts: [
        {
          object_key: 'exports/release-notes.pdf',
          url: 'https://artifacts.example/release-notes.pdf?signature=redacted',
          mime_type: 'application/pdf',
          size_bytes: 2_621_440,
          source: 'export_artifact',
        },
        {
          url: 'http://127.0.0.1:8000/api/v1/artifacts/artifact-2/download',
          size_bytes: 512,
        },
      ],
    }),
    [
      {
        key: 'https://artifacts.example/release-notes.pdf?signature=redacted\u0000exports/release-notes.pdf',
        label: 'release-notes.pdf',
        url: 'https://artifacts.example/release-notes.pdf?signature=redacted',
        mimeType: 'application/pdf',
        sizeBytes: 2_621_440,
        source: 'export_artifact',
      },
      {
        key: 'http://127.0.0.1:8000/api/v1/artifacts/artifact-2/download\u0000',
        label: 'download',
        url: 'http://127.0.0.1:8000/api/v1/artifacts/artifact-2/download',
        mimeType: null,
        sizeBytes: 512,
        source: null,
      },
    ],
  );
});

test('top-level artifacts take priority and stable duplicate references collapse', () => {
  const reference = {
    object_key: 'exports/report.csv',
    url: 'https://artifacts.example/report.csv',
    size_bytes: 1_024,
  };
  assert.deepEqual(
    assistantArtifactReferences({
      artifacts: [reference, { ...reference }],
      metadata: {
        artifacts: [
          {
            object_key: 'exports/metadata-only.txt',
            url: 'https://artifacts.example/metadata-only.txt',
          },
        ],
      },
    }),
    [
      {
        key: 'https://artifacts.example/report.csv\u0000exports/report.csv',
        label: 'report.csv',
        url: 'https://artifacts.example/report.csv',
        mimeType: null,
        sizeBytes: 1_024,
        source: null,
      },
    ],
  );
});

test('metadata artifacts support historical and workspace message shapes', () => {
  assert.deepEqual(
    assistantArtifactReferences({
      metadata: {
        artifacts: [
          {
            url: 'https://artifacts.example/design%20review.docx',
          },
        ],
      },
    }),
    [
      {
        key: 'https://artifacts.example/design%20review.docx\u0000',
        label: 'design review.docx',
        url: 'https://artifacts.example/design%20review.docx',
        mimeType: null,
        sizeBytes: null,
        source: null,
      },
    ],
  );
});

test('unsafe, malformed, and incomplete artifact references are ignored', () => {
  assert.deepEqual(
    assistantArtifactReferences({
      artifacts: [
        null,
        {},
        { url: '' },
        { url: 'javascript:alert(1)' },
        { url: 'file:///etc/passwd' },
        { url: 'data:text/html,unsafe' },
        { url: 'blob:https://artifacts.example/id' },
        { url: 'mailto:test@example.com' },
        { url: '/api/v1/artifacts/relative/download' },
        { url: 'http://artifacts.example/insecure.txt' },
        { url: 'http://[::1' },
        { url: 'contains whitespace.pdf' },
        { url: 'https://artifacts.example/valid.txt', size_bytes: -1 },
      ],
    }),
    [
      {
        key: 'https://artifacts.example/valid.txt\u0000',
        label: 'valid.txt',
        url: 'https://artifacts.example/valid.txt',
        mimeType: null,
        sizeBytes: null,
        source: null,
      },
    ],
  );
});

test('artifact byte sizes follow the existing desktop attachment scale', () => {
  assert.equal(formatAssistantArtifactSize(0), '0 B');
  assert.equal(formatAssistantArtifactSize(512), '512 B');
  assert.equal(formatAssistantArtifactSize(1_024), '1.0 KB');
  assert.equal(formatAssistantArtifactSize(2_621_440), '2.5 MB');
});

test('artifact links are keyboard-addressable downloads with safe window isolation', () => {
  assert.match(componentSource, /className="assistant-artifact-reference"/);
  assert.match(componentSource, /target="_blank"/);
  assert.match(componentSource, /rel="noopener noreferrer"/);
  assert.match(componentSource, /download/);
  assert.match(componentSource, /aria-label=\{reference\.label\}/);
});

test('agent timeline and workspace messages share artifact reference rendering', () => {
  assert.match(
    timelineSource,
    /<AssistantArtifactReferences[\s\S]*artifacts=\{item\.artifacts\}[\s\S]*metadata=\{item\.metadata\}/,
  );
  assert.match(
    transcriptSource,
    /<AssistantArtifactReferences[\s\S]*metadata=\{message\.metadata\}/,
  );
});

test('artifact-only replies do not expose the internal assistant event type as prose', () => {
  assert.match(
    timelineSource,
    /const content\s*=\s*kind === 'user' \|\| kind === 'agent'[\s\S]*item\.content \?\? ''[\s\S]*timelinePayloadPreview\(item\)/,
  );
});

test('execution summary emits the artifact-count metric exactly once', () => {
  assert.equal(
    (
      timelineSource.match(
        /pills\.push\(\{ label: t\('chat\.summary\.artifacts'\), value: String\(summary\.artifactCount\) \}\)/g,
      ) ?? []
    ).length,
    1,
  );
});

test('artifact references remain bounded and have a deterministic browser QA route', () => {
  assert.match(stylesSource, /\.assistant-artifact-references/);
  assert.match(stylesSource, /\.assistant-artifact-reference[\s\S]*max-width:\s*100%/);
  assert.match(stylesSource, /\.assistant-artifact-reference:focus-visible/);
  assert.match(qaSource, /Agent timeline/);
  assert.match(qaSource, /Workspace message/);
  assert.match(qaSource, /Artifact-only/);
  assert.match(qaSource, /Toggle narrow/);
});
