import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  canonicalStoryRenderDecision,
  parseCanonicalStory,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/canonicalStoryModel.js');

const readSource = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
const readOptionalSource = (path) => {
  const url = new URL(`../src/${path}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
};

const VALID_STORY = [
  'story:',
  '  version: 1',
  '  language: zh-CN',
  '  title: 对齐桌面会话渲染',
  '  problem_statement: Desktop currently renders structured stories as raw YAML.',
  '  user_value: Reviewers can scan acceptance and dependency state.',
  '  acceptance_criteria:',
  '    - id: AC-1',
  '      text: Valid stories render as one card.',
  '      testable: true',
  '    - id: AC-2',
  '      text: Ordinary YAML remains code.',
  '      testable: true',
  '  constraints_and_affected_areas:',
  '    - Desktop transcript',
  '  dependencies_and_sequencing:',
  '    independent_story_check: pass',
  '    depends_on: []',
  '    unblock_condition: No external dependency.',
  '  out_of_scope:',
  '    - Canvas lifecycle',
  '  invest:',
  '    independent: { status: pass, reason: Self-contained renderer. }',
  '    negotiable: { status: pass, reason: Presentation can evolve. }',
  '    valuable: { status: pass, reason: Improves reviewability. }',
  '    estimable: { status: pass, reason: Bounded component. }',
  '    small: { status: warning, reason: Includes deterministic QA. }',
  '    testable: { status: pass, reason: Schema and DOM are testable. }',
].join('\n');

test('valid canonical stories parse into bounded structured fields', () => {
  const result = parseCanonicalStory(VALID_STORY);

  assert.equal(result.issues.length, 0);
  assert.equal(result.story?.story.title, '对齐桌面会话渲染');
  assert.equal(result.story?.story.acceptance_criteria.length, 2);
  assert.equal(result.story?.story.invest.small.status, 'warning');
});

test('renderer uses explicit fence metadata and complete schema, never body keywords', () => {
  assert.equal(canonicalStoryRenderDecision('canonical-story', VALID_STORY).kind, 'card');
  assert.equal(canonicalStoryRenderDecision('yaml', VALID_STORY).kind, 'card');

  for (const [language, source] of [
    ['yaml', 'story: just a string'],
    ['yaml', 'title: story\nstatus: ready'],
    ['text', VALID_STORY],
    ['typescript', `const story = ${JSON.stringify(VALID_STORY)};`],
  ]) {
    assert.equal(
      canonicalStoryRenderDecision(language, source).kind,
      'code',
      `${language}: ${source.slice(0, 30)}`,
    );
  }
});

test('explicit invalid stories remain inspectable while ordinary invalid YAML stays code', () => {
  const invalid = 'story:\n  version: nope\n  title: Missing most required fields';
  const explicit = canonicalStoryRenderDecision('canonical-story', invalid);
  const ordinary = canonicalStoryRenderDecision('yaml', invalid);

  assert.equal(explicit.kind, 'card');
  assert.equal(explicit.result.story, null);
  assert.ok(explicit.result.issues.length > 0);
  assert.equal(explicit.result.rawYaml, invalid);
  assert.equal(ordinary.kind, 'code');
});

test('parser fails closed for duplicate IDs, aliases, oversized input, and excessive collections', () => {
  const duplicateIds = VALID_STORY.replace('id: AC-2', 'id: AC-1');
  assert.match(parseCanonicalStory(duplicateIds).issues.join('\n'), /acceptance_ids_not_unique/);

  const aliasStory = VALID_STORY.replace(
    'constraints_and_affected_areas:\n    - Desktop transcript',
    'constraints_and_affected_areas: &areas\n    - Desktop transcript\n  out_of_scope: *areas',
  ).replace('  out_of_scope:\n    - Canvas lifecycle\n', '');
  assert.match(parseCanonicalStory(aliasStory).issues.join('\n'), /aliases_forbidden/);

  assert.match(parseCanonicalStory('x'.repeat(65_537)).issues.join('\n'), /source_too_long:65536/);

  const tooManyConstraints = VALID_STORY.replace(
    '  constraints_and_affected_areas:\n    - Desktop transcript',
    `  constraints_and_affected_areas:\n${Array.from(
      { length: 51 },
      (_, index) => `    - area-${String(index)}`,
    ).join('\n')}`,
  );
  assert.match(parseCanonicalStory(tooManyConstraints).issues.join('\n'), /collection_limit/);
});

test('shared Markdown routes target fences through the card without disturbing existing renderers', () => {
  const transcriptSource = readSource('features/chat/ChatTranscript.tsx');
  const cardSource = readOptionalSource('features/chat/CanonicalStoryCard.tsx');
  const stylesSource = readOptionalSource('features/chat/CanonicalStoryCard.css');

  assert.match(transcriptSource, /canonicalStoryRenderDecision\(language,\s*code\)/);
  assert.match(transcriptSource, /<CanonicalStoryCard result=\{decision\.result\}/);
  assert.match(transcriptSource, /shouldRenderMermaidDiagram\(language\)/);
  assert.match(transcriptSource, /<CodeBlockFrame code=\{code\} language=\{language\}/);
  assert.match(cardSource, /aria-expanded=\{open\}/);
  assert.match(cardSource, /CodeBlockFrame code=\{result\.rawYaml\}/);
  assert.doesNotMatch(cardSource, /dangerouslySetInnerHTML|innerHTML/);
  assert.match(stylesSource, /\.canonical-story-card/);
  assert.match(stylesSource, /\.canonical-story-toggle:focus-visible/);
});

test('deterministic QA covers valid, invalid, ordinary YAML, themes, and narrow width', () => {
  const qaSource = readOptionalSource('qa/CanonicalStoryRenderingQa.tsx');
  const qaHtml = readFileSync(
    new URL('../qa/canonical-story-rendering.html', import.meta.url),
    'utf8',
  );

  assert.match(qaSource, /Valid story/);
  assert.match(qaSource, /Invalid explicit/);
  assert.match(qaSource, /Ordinary YAML/);
  assert.match(qaSource, /Toggle theme/);
  assert.match(qaSource, /Toggle narrow/);
  assert.match(qaSource, /data-testid="canonical-story-qa-scenario"/);
  assert.match(qaHtml, /CanonicalStoryRenderingQa\.tsx/);
});
