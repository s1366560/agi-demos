import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
const esbuild = createRequire(require.resolve('vite'))('esbuild');
const compiled = await esbuild.build({
  entryPoints: [new URL('../src/plugins/desktopProjectSandboxUploadResponseContractV2.ts', import.meta.url).pathname],
  bundle: true, write: false, platform: 'node', format: 'cjs', packages: 'external',
});
const module = { exports: {} };
new Function('require', 'module', 'exports', compiled.outputFiles[0].text)(require, module, module.exports);
const { requireSandboxUploadResultV2 } = module.exports;
const input = { file: { name: 'evidence.txt', size: 4, type: 'text/plain' } };
const response = (inner) => ({success: true, is_error: false, content: [{type: 'text', text: JSON.stringify(inner)}]});

test('sandbox business failure returns a fixed reason without exposing raw tool errors', () => {
  for (const raw of [
    response({success: false, error: 'private backend path or credential'}),
    {success: false, is_error: true, content: [{type: 'text', text: 'private backend path or credential'}]},
  ]) {
    assert.throws(() => requireSandboxUploadResultV2(raw, input), (error) => {
      assert.equal(error.message, 'project_sandbox_upload_tool_failed');
      assert.doesNotMatch(JSON.stringify(error), /private backend/);
      return true;
    });
  }
});

test('sandbox success still requires exact path and byte count; malformed envelopes stay invalid', () => {
  const valid = {success: true, path: '/workspace/input/evidence.txt', size_bytes: 4};
  assert.equal(requireSandboxUploadResultV2(response(valid), input).size_bytes, 4);
  for (const raw of [
    response({...valid, path: '/workspace/other.txt'}),
    response({...valid, size_bytes: 5}),
    response({success: 'false'}),
    {success: true, content: []},
    {success: false, is_error: false, content: null},
  ]) assert.throws(() => requireSandboxUploadResultV2(raw, input), /project_sandbox_upload_response_invalid/);
});


test('composer renders localized sandbox failure without exposing its protocol reason', async () => {
  const webRequire = createRequire(new URL('../../../../web/package.json', import.meta.url));
  const { Window } = await import(pathToFileURL(webRequire.resolve('happy-dom')).href);
  const window = new Window({ url: 'http://localhost/' });
  for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'Node']) {
    Object.defineProperty(globalThis, key, {
      configurable: true, value: key === 'window' ? window : window[key],
    });
  }
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const React = require('react');
  const { createRoot } = require('react-dom/client');
  const output = await esbuild.build({
    stdin: {
      contents: "export {useComposerFileUpload} from './src/features/chat/useComposerFileUpload'; export {I18nProvider} from './src/i18n';",
      resolveDir: new URL('..', import.meta.url).pathname,
      loader: 'ts',
    },
    bundle: true, write: false, platform: 'node', format: 'cjs', packages: 'external',
  });
  const hookModule = { exports: {} };
  new Function('require', 'module', 'exports', output.outputFiles[0].text)(require, hookModule, hookModule.exports);
  const { useComposerFileUpload, I18nProvider } = hookModule.exports;
  let hook;
  const api = { uploadSandboxFile: async () => { throw new Error('project_sandbox_upload_tool_failed'); } };
  const onAdd = () => { throw new Error('failed uploads cannot become attachment chips'); };
  function Harness() {
    hook = useComposerFileUpload({ api, onAdd });
    return React.createElement('div', null, hook.fileUploadErrors.join(' '));
  }
  const container = document.createElement('div');
  const root = createRoot(container);
  try {
    await React.act(async () => root.render(React.createElement(I18nProvider, null, React.createElement(Harness))));
    await React.act(async () => hook.uploadFiles([{ name: 'evidence.txt', size: 4 }]));
    assert.match(container.textContent, /sandbox could not save|沙箱未能保存文件/);
    assert.doesNotMatch(container.textContent, /project_sandbox_upload_tool_failed/);
  } finally {
    await React.act(async () => root.unmount());
    await window.happyDOM.close();
  }
});
