import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { mkdtemp, mkdir, realpath, rm, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { createServer } from 'vite';

import { rendererRootHotReload } from '../scripts/rendererRootHotReload.mjs';

const require = createRequire(import.meta.url);
const { RendererGenerationLeaseStoreV2 } = require(
  '/tmp/agistack-desktop-test-dist/packages/plugin-runtime/src/renderer.js',
);

const rootFile = '/desktop/src/plugins/useDesktopPluginGenerationV2.ts';

test('both renderer development entry points install the root lifecycle boundary', () => {
  for (const config of ['vite.config.ts', 'electron.vite.config.ts']) {
    const source = readFileSync(new URL(`../${config}`, import.meta.url), 'utf8');
    assert.match(source, /rendererRootHotReload\(/u);
  }
});
function module(file, importers = [], type = 'js') {
  return { file, importers: new Set(importers), type };
}

function update(modules) {
  const messages = [];
  const plugin = rendererRootHotReload('/desktop');
  const result = plugin.handleHotUpdate({
    modules,
    server: { ws: { send: (message) => messages.push(message) } },
  });
  return { result, messages };
}

test('root-owned store and transitive definition updates reload before partial replacement', () => {
  const root = module(rootFile);
  const definitions = module('/desktop/src/plugins/definitions.ts', [root]);
  const translations = module('/desktop/src/i18n.tsx', [definitions]);
  // Registry modules can form cycles and can also be React refresh boundaries.
  definitions.importers.add(translations);
  translations.isSelfAccepting = true;
  for (const changed of [root, definitions, translations]) {
    assert.deepEqual(update([changed]), {
      result: [],
      messages: [{ type: 'full-reload', path: '*' }],
    });
  }
});

test('CSS, unrelated modules and empty module updates retain normal HMR', () => {
  const root = module(rootFile);
  for (const changed of [
    [],
    [module('/desktop/src/styles/chrome.css', [root], 'css')],
    [module('/desktop/src/unrelated.ts')],
  ]) {
    assert.deepEqual(update(changed), { result: undefined, messages: [] });
  }
  assert.equal(rendererRootHotReload('/desktop').apply, 'serve');
});

test('one mixed update reloads once and suppresses all partial replacements', () => {
  const root = module(rootFile);
  assert.deepEqual(update([root, root, module('/desktop/src/other.ts', [root])]), {
    result: [],
    messages: [{ type: 'full-reload', path: '*' }],
  });
});

test('replacement store must be activated by a new root rather than an existing React tree', async () => {
  const runtime = { getSnapshot: () => undefined, subscribe: () => () => {} };
  const original = new RendererGenerationLeaseStoreV2(runtime);
  original.activateRoot();
  assert.doesNotThrow(() => original.getSnapshot());
  const replacement = new RendererGenerationLeaseStoreV2(runtime);
  assert.throws(() => replacement.getSnapshot(), { code: 'renderer_root_inactive' });

  const { result, messages } = update([module(rootFile)]);
  assert.deepEqual(result, []);
  assert.equal(messages[0].type, 'full-reload');
  // Suppressing module replacement leaves the live document's store valid
  // until the new document performs main.tsx's normal root activation.
  assert.doesNotThrow(() => original.getSnapshot());
  await original.deactivateRoot();
  assert.throws(() => original.getSnapshot(), { code: 'renderer_root_inactive' });
  replacement.activateRoot();
  assert.doesNotThrow(() => replacement.getSnapshot());
  assert.throws(() => replacement.activateRoot(), { code: 'renderer_root_already_active' });
  await replacement.deactivateRoot();
});

test('Vite module graph follows a changed translation through definitions to the root store', async () => {
  const directory = await realpath(await mkdtemp(join(tmpdir(), 'desktop-root-hmr-')));
  let server;
  try {
    await mkdir(join(directory, 'src/plugins'), { recursive: true });
    await writeFile(join(directory, 'src/i18n.ts'), 'export const label = "first";');
    await writeFile(
      join(directory, 'src/plugins/definitions.ts'),
      'import { label } from "../i18n"; export const definition = { label };',
    );
    await writeFile(
      join(directory, 'src/plugins/useDesktopPluginGenerationV2.ts'),
      'import { definition } from "./definitions"; export const store = { definition };',
    );
    const plugin = rendererRootHotReload(directory);
    server = await createServer({
      configFile: false,
      root: directory,
      plugins: [plugin],
      server: { middlewareMode: true, hmr: false, watch: null, preTransformRequests: false },
      optimizeDeps: { noDiscovery: true, include: [] },
    });
    await server.transformRequest('/src/plugins/useDesktopPluginGenerationV2.ts');
    await server.transformRequest('/src/plugins/definitions.ts');
    await server.transformRequest('/src/i18n.ts');
    const messages = [];
    const modules = [...server.moduleGraph.getModulesByFile(join(directory, 'src/i18n.ts'))];
    const result = plugin.handleHotUpdate({
      modules,
      server: { ws: { send: (message) => messages.push(message) } },
    });
    assert.deepEqual(result, []);
    assert.deepEqual(messages, [{ type: 'full-reload', path: '*' }]);
  } finally {
    await server?.close();
    await rm(directory, { recursive: true, force: true });
  }
});
