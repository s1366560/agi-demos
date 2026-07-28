import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  beginArtifactPreviewLoad,
  completeArtifactPreviewLoad,
  disposeArtifactPreview,
  emptyArtifactPreviewLifecycle,
  failArtifactPreviewLoad,
  planArtifactPreview,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/artifactPreviewModel.js');

function input(mimeType, overrides = {}) {
  return {
    artifactId: 'artifact-preview',
    mimeType,
    sizeBytes: 1024,
    integrity: 'ready',
    ...overrides,
  };
}

test('HTML preview uses authenticated bytes and an empty sandbox token set', () => {
  const plan = planArtifactPreview(input('text/html; charset=utf-8'));
  assert.deepEqual(plan, {
    kind: 'preview',
    renderer: 'html_iframe',
    mimeType: 'text/html',
    byteSource: 'authenticated_artifact_api',
    objectUrl: 'required',
    isolation: {
      kind: 'sandboxed_iframe',
      sandboxTokens: [],
      allowScripts: false,
      allowForms: false,
      allowNavigation: false,
    },
    transform: 'none',
  });
  assert.equal(Object.isFrozen(plan.isolation.sandboxTokens), true);
});

test('PDF, image, audio, and video previews consume controlled Blob URLs', () => {
  assert.deepEqual(planArtifactPreview(input('application/pdf')), {
    kind: 'preview',
    renderer: 'pdf_iframe',
    mimeType: 'application/pdf',
    byteSource: 'authenticated_artifact_api',
    objectUrl: 'required',
    isolation: { kind: 'blob_iframe' },
    transform: 'none',
  });

  for (const [mimeType, renderer] of [
    ['image/png', 'image'],
    ['image/jpeg', 'image'],
    ['audio/mpeg', 'audio'],
    ['audio/ogg', 'audio'],
    ['video/mp4', 'video'],
    ['video/webm', 'video'],
  ]) {
    assert.deepEqual(planArtifactPreview(input(mimeType)), {
      kind: 'preview',
      renderer,
      mimeType,
      byteSource: 'authenticated_artifact_api',
      objectUrl: 'required',
      isolation: { kind: 'element' },
      transform: 'none',
    });
  }
});

test('SVG requires sanitization and sandbox isolation before its Blob URL is shown', () => {
  assert.deepEqual(planArtifactPreview(input('image/svg+xml')), {
    kind: 'preview',
    renderer: 'sanitized_svg',
    mimeType: 'image/svg+xml',
    byteSource: 'authenticated_artifact_api',
    objectUrl: 'required',
    isolation: {
      kind: 'sandboxed_iframe',
      sandboxTokens: [],
      allowScripts: false,
      allowForms: false,
      allowNavigation: false,
    },
    transform: 'sanitize_svg',
  });
});

test('DOCX and XLSX use byte parsers without exposing arbitrary URLs', () => {
  assert.deepEqual(
    planArtifactPreview(
      input('application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
    ),
    {
      kind: 'preview',
      renderer: 'docx',
      mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      byteSource: 'authenticated_artifact_api',
      objectUrl: 'forbidden',
      isolation: { kind: 'sanitized_dom' },
      transform: 'docx_preview',
    },
  );
  assert.deepEqual(
    planArtifactPreview(
      input('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
    ),
    {
      kind: 'preview',
      renderer: 'xlsx',
      mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      byteSource: 'authenticated_artifact_api',
      objectUrl: 'forbidden',
      isolation: { kind: 'sanitized_table', sheetTabs: true },
      transform: 'sheetjs',
    },
  );
});

test('PPTX, legacy Office, corrupt, oversized, and unsupported files fall back to download', () => {
  for (const mimeType of [
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/msword',
    'application/vnd.ms-excel',
    'application/vnd.ms-powerpoint',
  ]) {
    assert.deepEqual(planArtifactPreview(input(mimeType)), {
      kind: 'download',
      mimeType,
      reason: 'office_preview_unavailable',
    });
  }

  assert.deepEqual(
    planArtifactPreview(input('application/pdf', { integrity: 'corrupt' })),
    {
      kind: 'download',
      mimeType: 'application/pdf',
      reason: 'corrupt_content',
    },
  );
  assert.deepEqual(
    planArtifactPreview(
      input('application/pdf', {
        sizeBytes: 10_000_001,
        maxPreviewBytes: 10_000_000,
      }),
    ),
    {
      kind: 'download',
      mimeType: 'application/pdf',
      reason: 'preview_size_limit',
    },
  );
  assert.deepEqual(planArtifactPreview(input('application/octet-stream')), {
    kind: 'download',
    mimeType: 'application/octet-stream',
    reason: 'unsupported_mime',
  });
});

test('preview lifecycle aborts replaced requests and revokes replaced or stale Blob URLs', () => {
  let lifecycle = emptyArtifactPreviewLifecycle();
  const first = beginArtifactPreviewLoad(lifecycle, {
    artifactId: 'artifact-a',
    scopeKey: 'project-1:tab-a',
  });
  lifecycle = first.state;
  assert.deepEqual(first.commands, []);
  assert.deepEqual(first.request, {
    requestId: 1,
    artifactId: 'artifact-a',
    scopeKey: 'project-1:tab-a',
  });

  const firstReady = completeArtifactPreviewLoad(lifecycle, 1, 'blob:first');
  lifecycle = firstReady.state;
  assert.deepEqual(firstReady.commands, []);
  assert.equal(lifecycle.active?.phase, 'ready');
  assert.equal(lifecycle.active?.objectUrl, 'blob:first');

  const second = beginArtifactPreviewLoad(lifecycle, {
    artifactId: 'artifact-b',
    scopeKey: 'project-1:tab-b',
  });
  lifecycle = second.state;
  assert.deepEqual(second.commands, [{ type: 'revoke_object_url', url: 'blob:first' }]);

  const third = beginArtifactPreviewLoad(lifecycle, {
    artifactId: 'artifact-c',
    scopeKey: 'project-2:tab-c',
  });
  lifecycle = third.state;
  assert.deepEqual(third.commands, [{ type: 'abort_request', requestId: 2 }]);

  const stale = completeArtifactPreviewLoad(lifecycle, 2, 'blob:stale');
  assert.equal(stale.state, lifecycle);
  assert.deepEqual(stale.commands, [{ type: 'revoke_object_url', url: 'blob:stale' }]);

  const current = completeArtifactPreviewLoad(lifecycle, 3, 'blob:current');
  lifecycle = current.state;
  assert.equal(lifecycle.active?.phase, 'ready');
  assert.equal(lifecycle.active?.objectUrl, 'blob:current');

  const disposed = disposeArtifactPreview(lifecycle);
  assert.deepEqual(disposed.state, {
    nextRequestId: 4,
    active: null,
  });
  assert.deepEqual(disposed.commands, [
    { type: 'revoke_object_url', url: 'blob:current' },
  ]);
});

test('preview lifecycle never accepts an arbitrary URL as a render source', () => {
  const started = beginArtifactPreviewLoad(emptyArtifactPreviewLifecycle(), {
    artifactId: 'artifact-a',
    scopeKey: 'project-1:tab-a',
  });
  const rejected = completeArtifactPreviewLoad(
    started.state,
    1,
    'https://untrusted.example/artifact',
  );
  assert.equal(rejected.state.active?.phase, 'failed');
  assert.equal(rejected.state.active?.objectUrl, null);
  assert.equal(rejected.state.active?.failureReason, 'invalid_object_url');
  assert.deepEqual(rejected.commands, []);
});

test('closing a loading preview aborts it and stale completion cannot reclaim the surface', () => {
  const started = beginArtifactPreviewLoad(emptyArtifactPreviewLifecycle(), {
    artifactId: 'artifact-a',
    scopeKey: 'workspace-1:tab-a',
  });
  const disposed = disposeArtifactPreview(started.state);
  assert.deepEqual(disposed.commands, [{ type: 'abort_request', requestId: 1 }]);

  const stale = completeArtifactPreviewLoad(disposed.state, 1, 'blob:late');
  assert.equal(stale.state, disposed.state);
  assert.deepEqual(stale.commands, [{ type: 'revoke_object_url', url: 'blob:late' }]);
});

test('failed loads release the request and a stale failure cannot replace newer state', () => {
  const first = beginArtifactPreviewLoad(emptyArtifactPreviewLifecycle(), {
    artifactId: 'artifact-a',
    scopeKey: 'project-1:tab-a',
  });
  const failed = failArtifactPreviewLoad(first.state, 1, 'decode_failed');
  assert.equal(failed.state.active?.phase, 'failed');
  assert.equal(failed.state.active?.failureReason, 'decode_failed');
  assert.deepEqual(failed.commands, []);

  const second = beginArtifactPreviewLoad(failed.state, {
    artifactId: 'artifact-b',
    scopeKey: 'project-1:tab-b',
  });
  const stale = failArtifactPreviewLoad(second.state, 1, 'late_failure');
  assert.equal(stale.state, second.state);
  assert.deepEqual(stale.commands, []);
});
