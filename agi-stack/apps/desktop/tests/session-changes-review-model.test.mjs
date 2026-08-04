import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  addChangeComment,
  buildChangeCommentsMessage,
  clearChangeComments,
  collapseAllChangeFiles,
  commentsForConversation,
  createChangeComment,
  expandAllChangeFiles,
  reconcileExpandedChangeFiles,
  referencesForChangeComments,
  removeChangeComment,
  toggleExpandedChangeFile,
} = require('/tmp/agistack-desktop-test-dist/src/features/session/sessionChangesReviewModel.js');

const reference = {
  type: 'code_range',
  snapshot_id: 'snapshot-1',
  environment_id: 'environment-1',
  path: 'src/lib.rs',
  start_line: 12,
  end_line: 12,
  side: 'new',
  patch_digest: 'patch-1',
};

const oldSideReference = {
  ...reference,
  path: 'src/types.ts',
  start_line: 9,
  end_line: 9,
  side: 'old',
};

const files = [
  { path: 'src/a.ts' },
  { path: 'src/b.ts' },
  { path: 'src/c.ts' },
];

test('createChangeComment trims text and rejects blank input', () => {
  const comment = createChangeComment(reference, '  why is this here?  ', 'c1', '2026-01-01T00:00:00Z');
  assert.deepEqual(comment, {
    id: 'c1',
    reference,
    text: 'why is this here?',
    createdAt: '2026-01-01T00:00:00Z',
  });
  assert.equal(createChangeComment(reference, '   ', 'c2', 'now'), null);
  assert.equal(createChangeComment(reference, 'text', '', 'now'), null);
});

test('comment map is keyed per conversation and updates immutably', () => {
  const first = createChangeComment(reference, 'first', 'c1', 't1');
  const second = createChangeComment(oldSideReference, 'second', 'c2', 't2');
  let map = {};
  map = addChangeComment(map, 'conversation-1', first);
  map = addChangeComment(map, 'conversation-1', second);
  map = addChangeComment(map, 'conversation-2', createChangeComment(reference, 'other', 'c3', 't3'));

  assert.equal(commentsForConversation(map, 'conversation-1').length, 2);
  assert.equal(commentsForConversation(map, 'conversation-2').length, 1);
  assert.deepEqual(commentsForConversation(map, null), []);
  assert.deepEqual(commentsForConversation(map, 'missing'), []);

  const afterRemove = removeChangeComment(map, 'conversation-1', 'c1');
  assert.deepEqual(
    commentsForConversation(afterRemove, 'conversation-1').map((comment) => comment.id),
    ['c2'],
  );
  assert.equal(commentsForConversation(map, 'conversation-1').length, 2, 'original map untouched');

  const afterClear = clearChangeComments(map, 'conversation-1');
  assert.deepEqual(commentsForConversation(afterClear, 'conversation-1'), []);
  assert.equal(commentsForConversation(afterClear, 'conversation-2').length, 1);
  assert.equal(clearChangeComments(map, 'missing'), map, 'clearing unknown id is a no-op');
});

test('batched references are deduplicated by structural anchor key', () => {
  const comments = [
    createChangeComment(reference, 'one', 'c1', 't1'),
    createChangeComment({ ...reference }, 'same line again', 'c2', 't2'),
    createChangeComment(oldSideReference, 'other', 'c3', 't3'),
  ];
  const references = referencesForChangeComments(comments);
  assert.equal(references.length, 2);
  assert.equal(references[0].path, 'src/lib.rs');
  assert.equal(references[1].path, 'src/types.ts');
});

test('batched message quotes each anchor with its indented comment text', () => {
  const comments = [
    createChangeComment(reference, 'rename this binding', 'c1', 't1'),
    createChangeComment(oldSideReference, 'first line\nsecond line', 'c2', 't2'),
  ];
  const message = buildChangeCommentsMessage(comments);
  assert.equal(
    message,
    [
      'Please address the following inline review comments:',
      '',
      '1. src/lib.rs#L12',
      '   rename this binding',
      '2. src/types.ts#L-9',
      '   first line',
      '   second line',
    ].join('\n'),
  );
});

test('file expansion toggles, expands all, collapses all', () => {
  assert.deepEqual(toggleExpandedChangeFile([], 'src/a.ts'), ['src/a.ts']);
  assert.deepEqual(toggleExpandedChangeFile(['src/a.ts'], 'src/b.ts'), ['src/a.ts', 'src/b.ts']);
  assert.deepEqual(toggleExpandedChangeFile(['src/a.ts'], 'src/a.ts'), []);
  assert.deepEqual(expandAllChangeFiles(files), ['src/a.ts', 'src/b.ts', 'src/c.ts']);
  assert.deepEqual(collapseAllChangeFiles(), []);
});

test('reconcile prunes vanished paths and falls back to the first file', () => {
  assert.deepEqual(reconcileExpandedChangeFiles(['src/b.ts', 'gone.ts'], files), ['src/b.ts']);
  assert.deepEqual(reconcileExpandedChangeFiles(['gone.ts'], files), ['src/a.ts']);
  assert.deepEqual(reconcileExpandedChangeFiles([], []), []);
});

test('changes review panel stays event-driven with no idle repaint sources', () => {
  const canvasSource = readFileSync(
    new URL('../src/features/session/SessionChangesCanvas.tsx', import.meta.url),
    'utf8',
  );
  const modelSource = readFileSync(
    new URL('../src/features/session/sessionChangesReviewModel.ts', import.meta.url),
    'utf8',
  );
  const cssSource = readFileSync(
    new URL('../src/features/session/SessionChangesCanvas.css', import.meta.url),
    'utf8',
  );
  for (const source of [canvasSource, modelSource]) {
    assert.doesNotMatch(source, /setInterval\(/);
    assert.doesNotMatch(source, /setTimeout\(/);
    assert.doesNotMatch(source, /requestAnimationFrame\(/);
  }
  assert.doesNotMatch(cssSource, /@keyframes/);
  assert.doesNotMatch(cssSource, /animation[^-]/);
  assert.doesNotMatch(cssSource, /infinite/);
});
