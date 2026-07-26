import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  artifactTimelineCard,
  formatArtifactTimelineSize,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/artifactTimelineCardModel.js');

const readSource = (path) =>
  readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
const readOptionalSource = (path) => {
  const url = new URL(`../src/${path}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
};

const componentSource = readOptionalSource('features/chat/ArtifactTimelineCard.tsx');
const timelineSource = readSource('features/chat/ChatTimeline.tsx');
const stylesSource = readSource('features/chat/ChatPanel.css');
const qaSource = readOptionalSource('qa/ArtifactTimelineCardQa.tsx');

test('created artifact without a URL renders a structured uploading card', () => {
  assert.deepEqual(
    artifactTimelineCard({
      id: 'artifact-created',
      type: 'artifact_created',
      eventTimeUs: 1,
      eventCounter: 1,
      payload: {
        artifact_id: 'artifact-1',
        filename: 'release-notes.md',
        mime_type: 'text/markdown',
        category: 'document',
        size_bytes: 2_048,
        source_tool: 'export_artifact',
      },
    }),
    {
      artifactId: 'artifact-1',
      filename: 'release-notes.md',
      mimeType: 'text/markdown',
      category: 'document',
      sizeBytes: 2_048,
      sourceTool: 'export_artifact',
      status: 'uploading',
      downloadUrl: null,
      previewUrl: null,
      previewKind: 'none',
      iconKind: 'document',
      error: null,
    },
  );
});

test('ready data updates the same artifact model with a safe download', () => {
  assert.deepEqual(
    artifactTimelineCard({
      id: 'artifact-created',
      type: 'artifact_created',
      eventTimeUs: 1,
      eventCounter: 1,
      artifactId: 'artifact-1',
      filename: 'report.pdf',
      mimeType: 'application/pdf',
      category: 'document',
      sizeBytes: 4_096,
      sourceTool: 'publish_report',
      payload: {
        url: 'https://artifacts.example/report.pdf',
      },
    }),
    {
      artifactId: 'artifact-1',
      filename: 'report.pdf',
      mimeType: 'application/pdf',
      category: 'document',
      sizeBytes: 4_096,
      sourceTool: 'publish_report',
      status: 'ready',
      downloadUrl: 'https://artifacts.example/report.pdf',
      previewUrl: null,
      previewKind: 'none',
      iconKind: 'document',
      error: null,
    },
  );
});

test('error state wins over a previously available URL and hides actions', () => {
  const card = artifactTimelineCard({
    id: 'artifact-created',
    type: 'artifact_created',
    eventTimeUs: 1,
    eventCounter: 1,
    artifactId: 'artifact-1',
    filename: 'broken.zip',
    mimeType: 'application/zip',
    sizeBytes: 100,
    url: 'https://artifacts.example/broken.zip',
    error: 'Upload checksum mismatch',
  });
  assert.equal(card.status, 'error');
  assert.equal(card.error, 'Upload checksum mismatch');
  assert.equal(card.downloadUrl, null);
  assert.equal(card.previewUrl, null);
  assert.equal(card.iconKind, 'archive');
});

test('safe structured image MIME enables a bounded image preview', () => {
  const card = artifactTimelineCard({
    id: 'artifact-created',
    type: 'artifact_created',
    eventTimeUs: 1,
    eventCounter: 1,
    payload: {
      artifact_id: 'artifact-image',
      filename: 'chart-output',
      mime_type: 'image/png',
      size_bytes: 12_000,
      url: 'https://artifacts.example/chart.png',
      preview_url: 'https://artifacts.example/chart-preview.png',
    },
  });
  assert.equal(card.status, 'ready');
  assert.equal(card.iconKind, 'image');
  assert.equal(card.previewKind, 'image');
  assert.equal(card.downloadUrl, 'https://artifacts.example/chart.png');
  assert.equal(card.previewUrl, 'https://artifacts.example/chart-preview.png');
});

test('unsafe artifact URLs retain status information without navigation', () => {
  for (const url of [
    'javascript:alert(1)',
    'file:///etc/passwd',
    'data:text/html,unsafe',
    'blob:https://artifacts.example/id',
    'http://artifacts.example/insecure',
    '/api/v1/artifacts/relative',
  ]) {
    const card = artifactTimelineCard({
      id: url,
      type: 'artifact_created',
      eventTimeUs: 1,
      eventCounter: 1,
      payload: {
        artifact_id: `artifact-${url}`,
        filename: 'structured-image',
        mime_type: 'image/png',
        url,
      },
    });
    assert.equal(card.status, 'ready');
    assert.equal(card.downloadUrl, null);
    assert.equal(card.previewUrl, null);
    assert.equal(card.previewKind, 'none');
  }
});

test('MIME icon selection never infers semantics from the filename or source tool', () => {
  const card = artifactTimelineCard({
    id: 'artifact-created',
    type: 'artifact_created',
    eventTimeUs: 1,
    eventCounter: 1,
    payload: {
      artifact_id: 'artifact-unknown',
      filename: 'looks-like-an-image.png',
      source_tool: 'image_generator',
    },
  });
  assert.equal(card.iconKind, 'file');
  assert.equal(card.previewKind, 'none');
});

test('artifact byte sizes share deterministic desktop formatting', () => {
  assert.equal(formatArtifactTimelineSize(0), '0 B');
  assert.equal(formatArtifactTimelineSize(512), '512 B');
  assert.equal(formatArtifactTimelineSize(1_024), '1.0 KB');
  assert.equal(formatArtifactTimelineSize(2_621_440), '2.5 MB');
  assert.equal(formatArtifactTimelineSize(2_147_483_648), '2.0 GB');
});

test('timeline renders the structured card as a first-class row instead of raw payload', () => {
  const timelineItemViewSource = timelineSource.slice(
    timelineSource.indexOf('function TimelineItemView'),
    timelineSource.indexOf('function TimelineItemBody'),
  );
  assert.match(
    timelineItemViewSource,
    /if \(kind === 'artifact'\)[\s\S]*<ArtifactTimelineCard item=\{item\}/,
  );
  assert.match(
    timelineSource,
    /node\.item\.type === 'artifact_created'[\s\S]*grouped\.push\(node\)/,
  );
  assert.doesNotMatch(
    timelineItemViewSource,
    /TimelinePayloadBlock/,
  );
});

test('artifact card exposes safe download and lazy image failure affordances', () => {
  assert.match(componentSource, /download=\{card\.filename\}/);
  assert.match(componentSource, /rel="noopener noreferrer"/);
  assert.match(componentSource, /loading="lazy"/);
  assert.match(componentSource, /onError=/);
  assert.match(componentSource, /artifact-timeline-preview-failed/);
  assert.doesNotMatch(componentSource, /refreshArtifact|refreshUrl|openCanvas|Canvas/);
});

test('artifact card styles and deterministic QA cover all lifecycle states', () => {
  assert.match(stylesSource, /\.artifact-timeline-card/);
  assert.match(stylesSource, /\.artifact-timeline-image/);
  assert.match(stylesSource, /max-width:\s*100%/);
  assert.match(qaSource, /Created/);
  assert.match(qaSource, /Ready image/);
  assert.match(qaSource, /Error/);
  assert.match(qaSource, /Unsafe URL/);
  assert.match(qaSource, /Toggle narrow/);
});
