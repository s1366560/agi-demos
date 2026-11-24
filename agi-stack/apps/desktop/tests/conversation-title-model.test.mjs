import assert from 'node:assert/strict';
import test from 'node:test';

import { compactWindowTitle } from '/tmp/agistack-desktop-test-dist/src/features/chrome/compactWindowTitle.js';

test('compacts long titles at a readable boundary without changing short ones', () => {
  assert.equal(compactWindowTitle('  hi  '), 'hi');
  assert.equal(compactWindowTitle(''), '');
  const english = 'Please write a long article about the history of artificial intelligence and its impact';
  const compactEnglish = compactWindowTitle(english, 48);
  assert.ok(compactEnglish.length <= 49);
  assert.match(compactEnglish, /…$/);
  assert.doesNotMatch(compactEnglish, /\s…$/);

  const chinese = '请用中文写一篇约一千字的文章，介绍人工智能的发展历史以及它对现代社会的深远影响';
  const compactChinese = compactWindowTitle(chinese, 24);
  assert.ok(compactChinese.length <= 25);
  assert.match(compactChinese, /…$/);
});

test('leaves a title at the limit unchanged', () => {
  const exact = 'x'.repeat(48);
  assert.equal(compactWindowTitle(exact, 48), exact);
});
