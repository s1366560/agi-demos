import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  mermaidThemeForAppearance,
  shouldRenderMermaidDiagram,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/mermaidDiagramModel.js',
);

const readSource = (path) =>
  readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
const readOptionalSource = (path) => {
  const url = new URL(`../src/${path}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
};

const transcriptSource = readSource('features/chat/ChatTranscript.tsx');
const mermaidSource = readOptionalSource('features/chat/MermaidBlock.tsx');
const sanitizerSource = readOptionalSource('features/chat/mermaidSvgSanitizer.ts');
const qaSource = readOptionalSource('qa/MermaidRenderingQa.tsx');
const stylesSource = readSource('features/chat/ChatPanel.css');
const i18nSource = readSource('i18n.tsx');
const packageSource = readFileSync(new URL('../package.json', import.meta.url), 'utf8');

test('only the exact structured Markdown language selects Mermaid rendering', () => {
  assert.equal(shouldRenderMermaidDiagram('mermaid'), true);
  for (const language of [
    'Mermaid',
    ' mermaid',
    'mermaid ',
    'mermaid-js',
    'flowchart',
    'diagram',
    'text',
    '',
    null,
    undefined,
  ]) {
    assert.equal(shouldRenderMermaidDiagram(language), false);
  }
});

test('Mermaid theme follows the explicit desktop appearance', () => {
  assert.equal(mermaidThemeForAppearance('dark'), 'dark');
  assert.equal(mermaidThemeForAppearance('light'), 'default');
});

test('Markdown routes exact Mermaid fences without changing ordinary code frames', () => {
  assert.match(transcriptSource, /shouldRenderMermaidDiagram\(language\)/);
  assert.match(transcriptSource, /<MermaidBlock chart=\{code\} \/>/);
  assert.match(transcriptSource, /<CodeBlockFrame code=\{code\} language=\{language\} \/>/);
});

test('Mermaid renderer is lazy, strict, cancellable, sanitized, and copyable', () => {
  assert.match(mermaidSource, /await import\('mermaid'\)/);
  assert.match(mermaidSource, /securityLevel:\s*'strict'/);
  assert.match(mermaidSource, /htmlLabels:\s*false/);
  assert.match(mermaidSource, /sanitizeMermaidSvg\(/);
  assert.match(mermaidSource, /cancelled\s*=\s*true/);
  assert.match(mermaidSource, /navigator\.clipboard\.writeText\(chart\)/);
  assert.match(mermaidSource, /<CodeBlockFrame[\s\S]*code=\{chart\}/);
  assert.match(
    mermaidSource,
    /aria-label=\{[\s\S]*chat\.mermaid\.copied[\s\S]*chat\.mermaid\.copySource/,
  );
});

test('SVG sanitizer uses explicit tag and attribute allow-lists', () => {
  assert.match(sanitizerSource, /ALLOWED_SVG_TAGS/);
  assert.match(sanitizerSource, /ALLOWED_SVG_ATTRIBUTES/);
  assert.match(sanitizerSource, /name\.startsWith\('on'\)/);
  assert.match(sanitizerSource, /javascript/);
  assert.match(sanitizerSource, /data:text/);
  assert.match(sanitizerSource, /foreignobject/);
});

test('Mermaid presentation is localized and constrained to the message width', () => {
  for (const key of [
    'chat.mermaid.copySource',
    'chat.mermaid.copied',
    'chat.mermaid.renderError',
  ]) {
    assert.match(i18nSource, new RegExp(`'${key.replaceAll('.', '\\.')}'`));
  }
  assert.match(stylesSource, /\.mermaid-block/);
  assert.match(stylesSource, /\.mermaid-block-canvas[\s\S]*overflow-x:\s*auto/);
  assert.match(stylesSource, /\.mermaid-block-canvas svg[\s\S]*max-width:\s*100%/);
});

test('Mermaid QA exercises valid, invalid, malicious, and ordinary code through MarkdownContent', () => {
  assert.match(qaSource, /<MarkdownContent/);
  assert.match(qaSource, /Valid diagram/);
  assert.match(qaSource, /Invalid diagram/);
  assert.match(qaSource, /Malicious diagram/);
  assert.match(qaSource, /Ordinary code/);
  assert.match(qaSource, /data-testid="mermaid-sanitizer-result"/);
  assert.match(packageSource, /"mermaid":\s*"\^11\.12\.2"/);
});
