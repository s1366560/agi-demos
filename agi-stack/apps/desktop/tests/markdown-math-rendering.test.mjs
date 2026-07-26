import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { hasMarkdownMathSyntax } = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/markdownMathModel.js',
);

const readSource = (path) =>
  readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
const readOptionalSource = (path) => {
  const url = new URL(`../src/${path}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
};

const modelSource = readOptionalSource('features/chat/markdownMathModel.ts');
const pluginsSource = readOptionalSource('features/chat/useMarkdownMathPlugins.ts');
const transcriptSource = readSource('features/chat/ChatTranscript.tsx');
const qaSource = readOptionalSource('qa/MarkdownMathRenderingQa.tsx');
const stylesSource = readSource('features/chat/ChatPanel.css');
const packageSource = readFileSync(new URL('../package.json', import.meta.url), 'utf8');

test('math syntax detection accepts inline and display Markdown delimiters', () => {
  for (const content of [
    '$E=mc^2$',
    'One symbol: $x$.',
    '$$\\frac{a}{b}$$',
    '$$\n\\begin{aligned}a&=b+c\\\\d&=e\\end{aligned}\n$$',
  ]) {
    assert.equal(hasMarkdownMathSyntax(content), true, content);
  }
});

test('math syntax detection rejects ordinary, escaped, currency, and incomplete text', () => {
  for (const content of [
    'No formula here.',
    'The price is $5 and the total is $10.',
    String.raw`Escaped delimiters stay raw: \$x\$`,
    'Streaming fragment: $E=mc',
    'Empty delimiters: $$$$',
    'Inline code stays literal: `$x$`.',
    ['```text', '$x$', '```'].join('\n'),
  ]) {
    assert.equal(hasMarkdownMathSyntax(content), false, content);
  }
});

test('math plugins and KaTeX styles load dynamically only after structural detection', () => {
  assert.match(modelSource, /hasMarkdownMathSyntax/);
  assert.match(pluginsSource, /hasMarkdownMathSyntax\(content\)/);
  assert.match(pluginsSource, /import\('remark-math'\)/);
  assert.match(pluginsSource, /import\('rehype-katex'\)/);
  assert.match(pluginsSource, /import\('katex\/dist\/katex\.min\.css'\)/);
  assert.match(pluginsSource, /cancelled\s*=\s*true/);
  assert.match(pluginsSource, /\.catch\(/);
});

test('shared transcript Markdown applies both lazy remark and rehype plugins', () => {
  assert.match(transcriptSource, /useMarkdownMathPlugins\(content\)/);
  assert.match(transcriptSource, /remarkPlugins=\{remarkPlugins\}/);
  assert.match(transcriptSource, /rehypePlugins=\{rehypePlugins\}/);
});

test('math presentation inherits message color and constrains display overflow', () => {
  assert.match(stylesSource, /\.markdown-content \.katex/);
  assert.match(stylesSource, /\.markdown-content \.katex-display[\s\S]*overflow-x:\s*auto/);
  assert.match(stylesSource, /\.markdown-content \.katex-display[\s\S]*max-width:\s*100%/);
});

test('math QA covers lazy, valid, incomplete, code, theme, and narrow states', () => {
  assert.match(qaSource, /Plain Markdown/);
  assert.match(qaSource, /Valid math/);
  assert.match(qaSource, /Incomplete math/);
  assert.match(qaSource, /Code dollar/);
  assert.match(qaSource, /Toggle theme/);
  assert.match(qaSource, /Toggle narrow/);
  assert.match(qaSource, /data-testid="math-qa-scenario"/);
});

test('desktop declares the same direct math rendering dependencies as Web', () => {
  assert.match(packageSource, /"katex":\s*"\^0\.16\.28"/);
  assert.match(packageSource, /"rehype-katex":\s*"\^7\.0\.1"/);
  assert.match(packageSource, /"remark-math":\s*"\^6\.0\.0"/);
});
