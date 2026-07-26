import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  normalizeMarkdownArtifactImagePath,
  resolveMarkdownArtifactImage,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/markdownArtifactImageModel.js');

const readSource = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
const readOptionalSource = (path) => {
  const url = new URL(`../src/${path}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
};

const imageArtifact = {
  artifact_id: 'artifact-chart',
  source_path: '/workspace/output/chart.png',
  object_key: 'tenant/project/chart.png',
  mime_type: 'image/png',
  url: 'https://artifacts.example/chart.png',
  preview_url: 'https://artifacts.example/chart-preview.png',
};

test('workspace aliases and dot segments normalize to one exact structural path', () => {
  assert.equal(
    normalizeMarkdownArtifactImagePath('~/output/./charts/../chart.png'),
    '/workspace/output/chart.png',
  );
  assert.equal(
    normalizeMarkdownArtifactImagePath('/workspace/output/%63hart.png'),
    '/workspace/output/chart.png',
  );
  assert.equal(normalizeMarkdownArtifactImagePath('/workspace/../../etc/passwd'), null);
  assert.equal(normalizeMarkdownArtifactImagePath('chart.png'), null);
});

test('an exact structured image path resolves the safe preview URL', () => {
  assert.deepEqual(
    resolveMarkdownArtifactImage('/workspace/output/chart.png', [
      {
        id: 'artifact-ready',
        type: 'artifact_ready',
        payload: imageArtifact,
      },
    ]),
    {
      key: '/workspace/output/chart.png\u0000https://artifacts.example/chart-preview.png',
      sourcePath: '/workspace/output/chart.png',
      url: 'https://artifacts.example/chart-preview.png',
      mimeType: 'image/png',
    },
  );
});

test('timeline, completion metadata, and artifact batches share the same resolver', () => {
  const carriers = [
    {
      id: 'top-level',
      type: 'artifact_ready',
      sourcePath: '/workspace/output/top.png',
      mimeType: 'image/png',
      url: 'http://127.0.0.1:5173/top.png',
    },
    {
      id: 'completion',
      type: 'assistant_message',
      metadata: {
        artifacts: [
          {
            source_path: '~/output/history.png',
            mime_type: 'image/png',
            url: 'https://artifacts.example/history.png',
          },
        ],
      },
    },
    {
      id: 'batch',
      type: 'artifacts_batch',
      payload: {
        artifacts: [
          {
            sandbox_path: '/workspace/output/batch.png',
            mime_type: 'image/webp',
            url: 'https://artifacts.example/batch.webp',
          },
        ],
      },
    },
  ];

  assert.equal(
    resolveMarkdownArtifactImage('/workspace/output/top.png', carriers)?.url,
    'http://127.0.0.1:5173/top.png',
  );
  assert.equal(
    resolveMarkdownArtifactImage('/workspace/output/history.png', carriers)?.url,
    'https://artifacts.example/history.png',
  );
  assert.equal(
    resolveMarkdownArtifactImage('/workspace/output/batch.png', carriers)?.url,
    'https://artifacts.example/batch.webp',
  );
});

test('one event may split authoritative artifact fields across its top level and payload', () => {
  assert.equal(
    resolveMarkdownArtifactImage('/workspace/output/split.png', [
      {
        id: 'split-artifact',
        type: 'artifact_ready',
        sourcePath: '/workspace/output/split.png',
        mimeType: 'image/png',
        payload: {
          preview_url: 'https://artifacts.example/split-preview.png',
          url: 'https://artifacts.example/split.png',
        },
      },
    ])?.url,
    'https://artifacts.example/split-preview.png',
  );
});

test('object keys and exact structured URLs resolve without filename guessing', () => {
  assert.equal(
    resolveMarkdownArtifactImage('tenant/project/chart.png', [{ artifacts: [imageArtifact] }])?.url,
    'https://artifacts.example/chart-preview.png',
  );
  assert.equal(
    resolveMarkdownArtifactImage('https://artifacts.example/chart.png', [
      { artifacts: [imageArtifact] },
    ])?.url,
    'https://artifacts.example/chart-preview.png',
  );
  assert.equal(resolveMarkdownArtifactImage('chart.png', [{ artifacts: [imageArtifact] }]), null);
});

test('only explicit image MIME and safe fetch URLs may resolve', () => {
  for (const url of [
    'javascript:alert(1)',
    'file:///etc/passwd',
    'data:image/png;base64,AAAA',
    'blob:https://artifacts.example/id',
    'http://artifacts.example/insecure.png',
    '/api/v1/artifacts/relative',
  ]) {
    assert.equal(
      resolveMarkdownArtifactImage('/workspace/output/chart.png', [
        {
          source_path: '/workspace/output/chart.png',
          mime_type: 'image/png',
          url,
        },
      ]),
      null,
    );
  }

  assert.equal(
    resolveMarkdownArtifactImage('/workspace/output/chart.png', [
      {
        source_path: '/workspace/output/chart.png',
        mime_type: 'application/octet-stream',
        url: 'https://artifacts.example/chart.png',
      },
    ]),
    null,
  );
});

test('ambiguous exact matches fail closed instead of choosing across artifacts', () => {
  assert.equal(
    resolveMarkdownArtifactImage('/workspace/output/chart.png', [
      {
        ...imageArtifact,
        url: 'https://artifacts.example/one.png',
        preview_url: undefined,
      },
      {
        ...imageArtifact,
        url: 'https://artifacts.example/two.png',
        preview_url: undefined,
      },
    ]),
    null,
  );
});

test('desktop Markdown image rendering is conversation-scoped and fetches into revocable blobs', () => {
  const componentSource = readOptionalSource('features/chat/MarkdownArtifactImage.tsx');
  const transcriptSource = readSource('features/chat/ChatTranscript.tsx');
  const timelineSource = readSource('features/chat/ChatTimeline.tsx');
  const stylesSource = readSource('features/chat/ChatPanel.css');
  const indexSource = readFileSync(new URL('../index.html', import.meta.url), 'utf8');

  assert.match(transcriptSource, /img:\s*MarkdownArtifactImage/);
  assert.match(transcriptSource, /MarkdownArtifactImageProvider[\s\S]*message/);
  assert.match(timelineSource, /MarkdownArtifactImageProvider[\s\S]*state\.items/);
  assert.match(componentSource, /new AbortController\(\)/);
  assert.match(componentSource, /URL\.createObjectURL/);
  assert.match(componentSource, /URL\.revokeObjectURL/);
  assert.match(componentSource, /credentials:\s*'omit'/);
  assert.match(componentSource, /referrerPolicy:\s*'no-referrer'/);
  assert.match(componentSource, /blob\.type\.toLowerCase\(\)\.startsWith\('image\/'\)/);
  assert.match(componentSource, /loading="lazy"/);
  assert.match(stylesSource, /\.markdown-artifact-image/);
  assert.match(stylesSource, /max-width:\s*100%/);
  assert.match(stylesSource, /object-fit:\s*contain/);
  assert.match(indexSource, /img-src 'self' blob: data:/);
  assert.doesNotMatch(indexSource, /img-src[^;]*https:/);
});

test('deterministic QA covers live, replay, unsafe, non-image, and narrow states', () => {
  const qaSource = readOptionalSource('qa/MarkdownArtifactImageQa.tsx');
  assert.match(qaSource, /Live pending/);
  assert.match(qaSource, /Live ready/);
  assert.match(qaSource, /History replay/);
  assert.match(qaSource, /Unsafe URL/);
  assert.match(qaSource, /Non-image MIME/);
  assert.match(qaSource, /Toggle narrow/);
});
