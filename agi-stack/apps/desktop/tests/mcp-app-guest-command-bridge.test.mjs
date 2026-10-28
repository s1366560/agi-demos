import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import ts from 'typescript';

const parse = (path) =>
  ts.createSourceFile(
    path,
    readFileSync(new URL(path, import.meta.url), 'utf8'),
    ts.ScriptTarget.Latest,
    true,
  );
const main = parse('../electron/main/index.ts');
const preload = parse('../electron/preload/index.ts');
const methods = ['open', 'start', 'update', 'layout', 'respond', 'release', 'prune', 'clear'];
const trustedUrl = 'agistack://desktop/index.html';
function declaration(ast, name) {
  let found;
  const visit = (node) => {
    if (
      (ts.isVariableDeclaration(node) || ts.isFunctionDeclaration(node)) &&
      node.name?.text === name
    )
      found = node;
    ts.forEachChild(node, visit);
  };
  visit(ast);
  assert.ok(found, name);
  return ts.isVariableDeclaration(found) ? `const ${found.getText(ast)};` : found.getText(ast);
}
function compile(source, bindings, name) {
  const code = ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.CommonJS,
    },
  }).outputText;
  return new Function(...Object.keys(bindings), `${code};return ${name};`)(
    ...Object.values(bindings),
  );
}
function fixture() {
  const calls = [];
  const frame = { url: trustedUrl };
  const contents = { id: 77, mainFrame: frame };
  const owner = { webContents: contents, isDestroyed: () => false };
  let event = { sender: contents, senderFrame: frame };
  const execute = compile(
    ['authorizedCloudRequestOwner', 'executeDesktopCommand']
      .map((name) => declaration(main, name))
      .join('\n'),
    {
      mainWindow: owner,
      rendererDevelopmentUrl: () => null,
      isTrustedNativeFileFrameUrl: (url) => url === trustedUrl,
      mcpAppGuestHost: Object.fromEntries(
        methods.map((method) => [
          method,
          (input) => {
            calls.push({ method, input });
            return method;
          },
        ]),
      ),
    },
    'executeDesktopCommand',
  );
  const invoke = compile(
    ['DESKTOP_COMMAND_CHANNEL', 'allowedCommands', 'invokeDesktopCommand']
      .map((name) => declaration(preload, name))
      .join('\n'),
    {
      ipcRenderer: {
        invoke(channel, command, input) {
          assert.equal(channel, 'agistack:desktop-command');
          return execute(event, command, input);
        },
      },
    },
    'invokeDesktopCommand',
  );
  return {
    calls,
    frame,
    contents,
    invoke,
    setEvent(value) {
      event = value;
    },
  };
}

test('all guest commands traverse the production preload and exact trusted main-frame gate', async () => {
  const f = fixture();
  for (const method of methods) assert.equal(await f.invoke(`mcp_app_guest_${method}`, {}), method);
  assert.deepEqual(
    f.calls.map((call) => call.method),
    methods,
  );
});

test('guest creation and cleanup both reject child frames, foreign owners and untrusted main URLs', async () => {
  const f = fixture();
  for (const event of [
    { sender: f.contents, senderFrame: { url: trustedUrl } },
    { sender: { id: 88, mainFrame: f.frame }, senderFrame: f.frame },
    { sender: f.contents, senderFrame: null },
  ]) {
    f.setEvent(event);
    for (const method of methods)
      await assert.rejects(f.invoke(`mcp_app_guest_${method}`, {}), /not authorized/u);
  }
  f.setEvent({ sender: f.contents, senderFrame: f.frame });
  f.frame.url = 'https://untrusted.example/';
  for (const method of methods)
    await assert.rejects(f.invoke(`mcp_app_guest_${method}`, {}), /not authorized/u);
  assert.equal(f.calls.length, 0);
  await assert.rejects(f.invoke('mcp_app_guest_unlisted', {}), /not supported/u);
});
