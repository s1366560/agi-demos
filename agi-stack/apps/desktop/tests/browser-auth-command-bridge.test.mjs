import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const source = path => {
  const content = readFileSync(new URL(path, import.meta.url), 'utf8');
  return ts.createSourceFile(path, content, ts.ScriptTarget.Latest, true);
};
const main = source('../electron/main/index.ts');
const preload = source('../electron/preload/index.ts');
function declaration(ast, name) {
  let result;
  function visit(node) {
    if ((ts.isFunctionDeclaration(node) || ts.isVariableDeclaration(node)) && node.name?.text === name) result = node;
    ts.forEachChild(node, visit);
  }
  visit(ast);
  assert.ok(result, `production declaration ${name}`);
  return ts.isVariableDeclaration(result) ? `const ${result.getText(ast)};` : result.getText(ast);
}
function compile(text, bindings, name) {
  const output = ts.transpileModule(text, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS,
  } }).outputText;
  return new Function(...Object.keys(bindings), `${output}; return ${name};`)(...Object.values(bindings));
}
function fixture() {
  const calls = [], mainFrame = { url: 'app://desktop/index.html' };
  const contents = { id: 7, mainFrame };
  const mainWindow = { webContents: contents, isDestroyed: () => false };
  let event = { sender: contents, senderFrame: mainFrame };
  const execute = compile(['SIDECAR_COMMANDS', 'authorizedCloudRequestOwner', 'executeDesktopCommand']
    .map(name => declaration(main, name)).join('\n'), {
    mainWindow, rendererDevelopmentUrl: () => null,
    isTrustedNativeFileFrameUrl: url => url === mainFrame.url,
    sidecarSupervisor: { invoke: async (command, args) => {
      calls.push({ command, args }); return { requests: [], accepted: true };
    } },
  }, 'executeDesktopCommand');
  const invoke = compile(['DESKTOP_COMMAND_CHANNEL', 'allowedCommands', 'invokeDesktopCommand']
    .map(name => declaration(preload, name)).join('\n'), {
    ipcRenderer: { invoke: (channel, command, args) => {
      assert.equal(channel, 'agistack:desktop-command');
      return execute(event, command, args);
    } },
  }, 'invokeDesktopCommand');
  return { calls, invoke, execute, setEvent: value => { event = value; }, contents, mainFrame };
}

test('browser authentication polling and responses traverse the actual preload and main command handlers', async () => {
  const bridge = fixture();
  const pending = { conversation_id: 'fixture-conversation' };
  assert.deepEqual(await bridge.invoke('browser_auth_pending', pending), { requests: [], accepted: true });
  const response = { ...pending, request_id: 'fixture-request', response: { action: 'decline' } };
  await bridge.invoke('browser_auth_respond', response);
  assert.deepEqual(bridge.calls, [
    { command: 'browser_auth_pending', args: pending },
    { command: 'browser_auth_respond', args: response },
  ]);
});

test('browser authentication rejects child frames and foreign renderer owners before reaching the sidecar', async () => {
  const bridge = fixture();
  for (const event of [
    { sender: bridge.contents, senderFrame: { url: bridge.mainFrame.url } },
    { sender: { id: 99 }, senderFrame: bridge.mainFrame },
  ]) {
    bridge.setEvent(event);
    for (const command of ['browser_auth_pending', 'browser_auth_respond']) {
      await assert.rejects(bridge.invoke(command, {}), /not authorized/u);
    }
  }
  await assert.rejects(bridge.invoke('browser_auth_unlisted', {}), /not supported/u);
  assert.equal(bridge.calls.length, 0);
});
