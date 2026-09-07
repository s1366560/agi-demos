import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const ts = require('typescript');
function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function harness(upload) {
  const slots = [];
  let cursor = 0;
  let effects = [];
  const equal = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const react = {
    useState(value) {
      const i = cursor++;
      slots[i] ??= { value };
      return [
        slots[i].value,
        (v) => {
          slots[i].value = v;
        },
      ];
    },
    useRef(value) {
      return (slots[cursor++] ??= { current: value });
    },
    useMemo(fn, deps) {
      const i = cursor++;
      if (!equal(slots[i]?.deps, deps)) slots[i] = { deps, value: fn() };
      return slots[i].value;
    },
    useCallback(fn, deps) {
      return react.useMemo(() => fn, deps);
    },
    useEffect(effect, deps) {
      const i = cursor++;
      if (!equal(slots[i]?.deps, deps))
        effects.push(() => {
          slots[i]?.cleanup?.();
          slots[i] = { deps, effect, cleanup: effect() };
        });
    },
  };
  const cache = new Map();
  function load(url) {
    if (cache.has(url.href)) return cache.get(url.href);
    const module = { exports: {} };
    cache.set(url.href, module.exports);
    const code = ts.transpileModule(readFileSync(url, 'utf8'), {
      fileName: url.pathname,
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.CommonJS,
      },
    }).outputText;
    new Function('require', 'module', 'exports', code)(
      (name) => {
        if (name === 'react') return react;
        if (name === '../../i18n')
          return { useI18n: () => ({ t: (key, args) => `${key}:${JSON.stringify(args)}` }) };
        return load(new URL(`${name}.ts`, url));
      },
      module,
      module.exports,
    );
    return module.exports;
  }
  const { useComposerFileUpload } = load(
    new URL('../src/features/chat/useComposerFileUpload.ts', import.meta.url),
  );
  const added = [];
  let props = {
    api: { uploadSandboxFile: upload },
    contextKey: 'context-one',
    onAdd: (item) => added.push(item),
  };
  function render(next = {}) {
    props = { ...props, ...next };
    cursor = 0;
    effects = [];
    const result = useComposerFileUpload(props);
    for (const effect of effects) effect();
    return result;
  }
  return {
    render,
    added,
    unmount() {
      for (const slot of slots) slot?.cleanup?.();
    },
    replay() {
      for (const slot of slots)
        if (slot?.effect) {
          slot.cleanup?.();
          slot.cleanup = slot.effect();
        }
    },
  };
}
const file = (name, size = 3) => ({
  name,
  size,
  type: 'text/plain',
  arrayBuffer: async () => new ArrayBuffer(3),
});
const metadata = (name) => ({
  filename: name,
  sandbox_path: `/uploads/${name}`,
  size: 3,
  mime_type: 'text/plain',
});
for (const interruption of ['context', 'api', 'unmount']) {
  test(`${interruption} cancels an upload, blocks the next file and rejects stale callbacks`, async () => {
    const wait = deferred();
    const calls = [];
    let signal;
    const h = harness(async (value, requestSignal) => {
      calls.push(value.name);
      signal = requestSignal;
      return wait.promise;
    });
    const old = h.render();
    const pending = old.uploadFiles([file('one'), file('two')]);
    if (interruption === 'context') h.render({ contextKey: 'context-two' });
    else if (interruption === 'api')
      h.render({ api: { uploadSandboxFile: async (value) => metadata(value.name) } });
    else h.unmount();
    assert.equal(signal.aborted, true);
    wait.resolve(metadata('one'));
    await pending;
    await old.uploadFiles([file('stale')]);
    old.rejectFileDrop();
    assert.deepEqual(calls, ['one']);
    assert.deepEqual(h.added, []);
    if (interruption !== 'unmount') {
      const current = h.render();
      assert.equal(current.uploadingFileCount, 0);
      assert.deepEqual(current.fileUploadErrors, []);
    }
  });
}
test('a newer batch owns progress and attachments while an old HTTP response arrives late', async () => {
  const first = deferred();
  const second = deferred();
  const h = harness((value) => (value.name === 'one' ? first.promise : second.promise));
  const old = h.render().uploadFiles([file('one')]);
  const next = h.render().uploadFiles([file('two')]);
  first.resolve(metadata('one'));
  await old;
  assert.equal(h.render().uploadingFileCount, 1);
  assert.deepEqual(h.added, []);
  second.resolve(metadata('two'));
  await next;
  assert.deepEqual(
    h.added.map((v) => v.label),
    ['two'],
  );
  assert.equal(h.render().uploadingFileCount, 0);
});
test('sequential success, oversize and ordinary failure preserve order and report failures', async () => {
  const calls = [];
  const h = harness(async (value, signal) => {
    assert.ok(signal instanceof AbortSignal);
    calls.push(value.name);
    if (value.name === 'bad') throw new Error('upload denied');
    return metadata(value.name);
  });
  const current = h.render();
  h.replay();
  await current.uploadFiles([file('one'), file('large', 17 * 1048576), file('bad'), file('two')]);
  assert.deepEqual(calls, ['one', 'bad', 'two']);
  assert.deepEqual(
    h.added.map((v) => v.label),
    ['one', 'two'],
  );
  assert.equal(h.render().fileUploadErrors.length, 2);
  assert.equal(h.render().uploadingFileCount, 0);
});
test('a byte-read promise resolving after context switch cannot append an attachment', async () => {
  const bytes = deferred();
  let signal;
  let sends = 0;
  const h = harness(async (value, requestSignal) => {
    signal = requestSignal;
    await value.arrayBuffer();
    requestSignal.throwIfAborted();
    sends++;
    return metadata(value.name);
  });
  const pending = h.render().uploadFiles([{ ...file('one'), arrayBuffer: () => bytes.promise }]);
  h.render({ contextKey: 'context-two' });
  bytes.resolve(new ArrayBuffer(3));
  await pending;
  assert.equal(signal.aborted, true);
  assert.equal(sends, 0);
  assert.deepEqual(h.added, []);
});

// Evaluate the actual caller's destructured props and context expression. This
// catches references to identifiers belonging to another component in the file.
function callerContext(path, functionName, props) {
  const source = ts.createSourceFile(
    path,
    readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8'),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  let declaration;
  const walk = (node, predicate) => {
    if (predicate(node)) return node;
    return ts.forEachChild(node, (child) => walk(child, predicate));
  };
  declaration = walk(
    source,
    (node) => ts.isFunctionDeclaration(node) && node.name?.text === functionName,
  );
  assert.ok(declaration);
  const call = walk(
    declaration.body,
    (node) =>
      ts.isCallExpression(node) && node.expression.getText(source) === 'useComposerFileUpload',
  );
  const expression = call.arguments[0].properties.find(
    (node) => node.name?.getText(source) === 'contextKey',
  ).initializer;
  const conversation = walk(
    declaration.body,
    (node) =>
      ts.isVariableDeclaration(node) && node.name.getText(source) === 'promptTemplateConversation',
  );
  const code = ts.transpileModule(
    `return (function(${declaration.parameters[0].getText(source)}) {
    ${conversation ? `const ${conversation.getText(source)};` : ''}
    return ${expression.getText(source)};
  })(props);`,
    { fileName: 'caller.ts', compilerOptions: { target: ts.ScriptTarget.ES2022 } },
  ).outputText;
  return new Function('props', 'EMPTY_AGENT_CONTROL_EVENTS', code)(props, []);
}

test('ChatComposer actual prop scope cancels uploads when the active conversation changes', async () => {
  const base = {
    conversations: [{ id: 'one', tenant_id: 'tenant', project_id: 'project' }],
    activeConversationId: 'one',
    selectedConversationId: 'one',
    composeAheadScope: 'scope-one',
  };
  const context = (props) => callerContext('features/chat/ChatPanel.tsx', 'ChatComposer', props);
  const first = context(base);
  const second = context({ ...base, activeConversationId: 'two' });
  assert.notEqual(first, second);
  const wait = deferred();
  const h = harness(() => wait.promise);
  const pending = h.render({ contextKey: first }).uploadFiles([file('one')]);
  h.render({ contextKey: second });
  wait.resolve(metadata('one'));
  await pending;
  assert.deepEqual(h.added, []);
});

test('NewThreadComposer actual workspace props produce a new upload context', () => {
  const context = (workspaceId) =>
    callerContext('features/task/NewThreadComposer.tsx', 'NewThreadComposer', {
      workspaceId,
      workspace: { tenant_id: 'tenant', project_id: 'project' },
    });
  assert.notEqual(context('workspace-one'), context('workspace-two'));
});
