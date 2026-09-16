import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  return readFileSync(new URL(`../${relativePath}`, import.meta.url), 'utf8');
}

const MODULES = Object.freeze([
  'src/plugins/desktopConversationRendererModuleV2.ts',
  'src/plugins/desktopToolResultRendererModuleV2.ts',
]);

function inlineScriptOf(moduleSource) {
  const match = moduleSource.match(/<script>([\s\S]*?)<\/script>/u);
  assert.ok(match, 'plugin renderer module must embed exactly one inline bootstrap script');
  return match[1];
}

function scriptHashOf(moduleSource) {
  const digest = createHash('sha256').update(inlineScriptOf(moduleSource), 'utf8').digest('base64');
  return `sha256-${digest}`;
}

function cspOf(documentSource) {
  const match = documentSource.match(
    /http-equiv="Content-Security-Policy"\s+content="([^"]+)"/u,
  );
  assert.ok(match, 'document must declare a Content-Security-Policy meta');
  return match[1];
}

const indexHtml = source('index.html');
const shellCsp = cspOf(indexHtml);

test('plugin renderer srcdoc CSP pins its own bootstrap script by sha256', () => {
  for (const modulePath of MODULES) {
    const moduleSource = source(modulePath);
    const csp = cspOf(moduleSource);
    const hash = scriptHashOf(moduleSource);
    assert.match(csp, /default-src 'none'/u, `${modulePath} keeps a fail-closed default`);
    assert.ok(
      csp.includes(`script-src '${hash}'`),
      `${modulePath} script-src must pin its inline bootstrap via '${hash}'`,
    );
    assert.doesNotMatch(
      csp,
      /script-src[^;]*'unsafe-inline'/u,
      `${modulePath} must not broadly allow inline scripts`,
    );
    assert.match(csp, /connect-src 'none'/u, `${modulePath} keeps network access disabled`);
  }
});

test('shell CSP admits exactly the pinned plugin renderer scripts for srcdoc inheritance', () => {
  // about:srcdoc documents initialize their CSP list from the embedder, so the
  // shell policy must also allow the two builtin sandbox bootstrap scripts.
  for (const modulePath of MODULES) {
    const hash = scriptHashOf(source(modulePath));
    assert.ok(
      shellCsp.includes(`'${hash}'`),
      `index.html script-src must inherit-admit '${hash}' for ${modulePath}`,
    );
  }
  assert.doesNotMatch(
    shellCsp,
    /script-src[^;]*'unsafe-inline'/u,
    'shell script-src must never allow arbitrary inline scripts',
  );
});
