import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
};
const source = '/workspace/output/chart.png';
const carriers = [
  { source_path: source, mime_type: 'image/png', url: 'https://images.example/chart.png' },
];
const owner = { kind: 'conversation', tenantId: 't', projectId: 'p', id: 'c' };
function harness() {
  const slots = [];
  let cursor = 0,
    effects = [],
    contextValue = { client: null, carriers };
  const equal = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const react = {
    createContext: () => ({ Provider: 'provider' }),
    useContext: () => contextValue,
    useRef(v) {
      return (slots[cursor++] ??= { current: v });
    },
    useMemo(fn, deps) {
      const i = cursor++;
      if (!equal(slots[i]?.deps, deps)) slots[i] = { deps, value: fn() };
      return slots[i].value;
    },
    useState(initial) {
      const i = cursor++;
      slots[i] ??= { value: typeof initial === 'function' ? initial() : initial };
      return [
        slots[i].value,
        (v) => {
          slots[i].value = typeof v === 'function' ? v(slots[i].value) : v;
        },
      ];
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
  const created = [],
    revoked = [];
  const urlApi = {
    createObjectURL(blob) {
      const url = `blob:preview-${created.length}`;
      created.push({ blob, url });
      return url;
    },
    revokeObjectURL(url) {
      revoked.push(url);
    },
  };
  function load(name) {
    const url = new URL(`../src/features/chat/${name}`, import.meta.url);
    const module = { exports: {} };
    const code = ts.transpileModule(readFileSync(url, 'utf8'), {
      fileName: url.pathname,
      compilerOptions: {
        jsx: ts.JsxEmit.ReactJSX,
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    }).outputText;
    new Function('require', 'module', 'exports', 'URL', 'IntersectionObserver', code)(
      (name) => {
        if (name === 'react') return react;
        if (name === 'react/jsx-runtime')
          return {
            jsx: (type, props) => ({ type, props }),
            jsxs: (type, props) => ({ type, props }),
          };
        if (name === '../../i18n') return { useI18n: () => ({ t: (key) => key }) };
        if (name === '../../plugins/desktopStructuredImagePreviewContractV2')
          return load('../../plugins/desktopStructuredImagePreviewContractV2.ts');
        if (!name.startsWith('.')) return require(name);
        const dependency = new URL(name + '.js', url).pathname.split('/src/')[1];
        return require('/tmp/agistack-desktop-test-dist/src/' + dependency);
      },
      module,
      module.exports,
      urlApi,
      undefined,
    );
    return module.exports;
  }
  const component = load('MarkdownArtifactImage.tsx');
  const guards = load('structuredImagePreviewOwnerModel.ts');
  let props = { src: source, alt: 'Chart' };
  function render(context = contextValue, nextProps = props, commit = true) {
    contextValue = context;
    props = nextProps;
    cursor = 0;
    const tree = component.MarkdownArtifactImage(props);
    if (commit) for (const effect of effects.splice(0)) effect();
    return tree;
  }
  function unmount() {
    for (const slot of slots) slot?.cleanup?.();
  }
  function strict() {
    unmount();
    for (const slot of slots) if (slot?.effect) slot.cleanup = slot.effect();
  }
  return { render, unmount, strict, created, revoked, guards };
}
const tick = () => new Promise(setImmediate);

test('explicit null client displays unavailable and performs zero loads', () => {
  const h = harness();
  const tree = h.render();
  assert.match(tree.props.className, /is-unavailable/);
  assert.equal(h.created.length, 0);
});
test('structured client receives unchanged carriers/source and one abort signal; URL revoked on unmount', async () => {
  const h = harness();
  let input;
  const blob = new Blob(['image'], { type: 'image/png' });
  const client = {
    owner,
    async loadImage(value) {
      input = value;
      return blob;
    },
  };
  h.render({ client, carriers });
  await tick();
  const tree = h.render();
  assert.deepEqual(input.carriers, carriers);
  assert.ok(Object.isFrozen(input.carriers));
  assert.equal(input.source, source);
  assert.equal(input.signal.aborted, false);
  assert.equal(tree.props.children.type, 'img');
  assert.equal(tree.props.children.props.src, 'blob:preview-0');
  h.unmount();
  assert.equal(input.signal.aborted, true);
  assert.deepEqual(h.revoked, ['blob:preview-0']);
});
for (const change of ['client', 'owner', 'carriers', 'unmount', 'strict'])
  test(`late Blob is ignored after ${change}`, async () => {
    const h = harness();
    const first = deferred();
    let signal;
    let loads = 0;
    const client = {
      owner,
      loadImage(input) {
        if (loads++ === 0) {
          signal = input.signal;
          return first.promise;
        }
        return change === 'strict'
          ? Promise.resolve(new Blob(['image'], { type: 'image/png' }))
          : new Promise(() => {});
      },
    };
    h.render({ client, carriers });
    if (change === 'unmount') h.unmount();
    else if (change === 'strict') h.strict();
    else
      h.render({
        client:
          change === 'client' || change === 'owner'
            ? {
                owner: { ...owner, id: change === 'owner' ? 'other' : 'c' },
                loadImage: () => new Promise(() => {}),
              }
            : client,
        carriers: change === 'carriers' ? [{ ...carriers[0], conversation_id: 'other' }] : carriers,
      });
    first.resolve(new Blob(['image'], { type: 'image/png' }));
    await tick();
    if (change === 'strict') {
      assert.equal(h.created.length, 1);
      h.unmount();
      assert.equal(h.revoked.length, 1);
    } else assert.equal(h.created.length, 0);
    assert.equal(signal.aborted, true);
  });
test('rendered client change hides old URL before passive cleanup and ignores old img error', async () => {
  const h = harness();
  const client = { owner, loadImage: async () => new Blob(['image'], { type: 'image/png' }) };
  h.render({ client, carriers });
  await tick();
  const old = h.render().props.children;
  const next = { owner: { ...owner, id: 'next' }, loadImage: () => new Promise(() => {}) };
  const tree = h.render({ client: next, carriers }, undefined, false);
  assert.notEqual(tree.props.children?.type, 'img');
  old.props.onError();
  assert.deepEqual(h.revoked, []);
  h.unmount();
  assert.deepEqual(h.revoked, ['blob:preview-0']);
});
test('decode error revokes once and marks unavailable; cleanup never revokes twice', async () => {
  const h = harness();
  h.render({
    client: { owner, loadImage: async () => new Blob(['image'], { type: 'image/png' }) },
    carriers,
  });
  await tick();
  h.render().props.children.props.onError();
  assert.match(h.render().props.className, /is-unavailable/);
  h.unmount();
  assert.equal(h.revoked.length, 1);
});
test('timeline mismatch and explicit workspace conflict disable client without fabricating missing owner fields', async () => {
  const h = harness();
  let calls = 0;
  const client = {
    owner,
    loadImage: async () => {
      calls++;
      return new Blob(['image'], { type: 'image/png' });
    },
  };
  const { conversationImagePreviewClient, workspaceImagePreviewClient } = h.guards;
  h.render({ client: conversationImagePreviewClient(client, 'other'), carriers });
  await tick();
  assert.equal(calls, 0);
  const workspace = { ...client, owner: { ...owner, kind: 'workspace', id: 'w' } };
  h.render({ client: workspaceImagePreviewClient(workspace, { workspace_id: 'other' }), carriers });
  await tick();
  assert.equal(calls, 0);
  assert.equal(conversationImagePreviewClient(workspace, 'w'), null);
  assert.equal(workspaceImagePreviewClient(client, {}), null);
  const missing = {};
  assert.equal(workspaceImagePreviewClient(workspace, missing), workspace);
  assert.deepEqual(missing, {});
});
test('carrier refresh can make a previously unresolved preview available', async () => {
  const h = harness();
  let calls = 0;
  const client = {
    owner,
    loadImage: async () => {
      calls++;
      return new Blob(['image'], { type: 'image/png' });
    },
  };
  h.render({ client, carriers: [] });
  await tick();
  assert.equal(calls, 0);
  h.render({ client, carriers });
  await tick();
  assert.equal(calls, 1);
  assert.equal(h.created.length, 1);
  h.unmount();
});
test('production owner guards and required injection are wired through both transcript paths', () => {
  const read = (name) =>
    readFileSync(new URL(`../src/features/chat/${name}`, import.meta.url), 'utf8');
  const panel = read('ChatPanel.tsx'),
    timeline = read('ChatTimeline.tsx'),
    transcript = read('ChatTranscript.tsx'),
    image = read('MarkdownArtifactImage.tsx');
  assert.match(panel, /imagePreviewClient: StructuredImagePreviewClientV2 \| null/u);
  assert.match(panel, /<AgentTimeline\s+imagePreviewClient=\{imagePreviewClient\}/u);
  assert.match(panel, /<WorkspaceTranscriptMessage\s+imagePreviewClient=\{imagePreviewClient\}/u);
  assert.match(
    timeline,
    /client=\{conversationImagePreviewClient\(imagePreviewClient, state.conversationId\)\}/u,
  );
  assert.match(
    transcript,
    /client=\{workspaceImagePreviewClient\(imagePreviewClient, message\)\}/u,
  );
  assert.match(image, /activeClient.loadImage/u);
  assert.doesNotMatch(image, /\bfetch\(/u);
});

test('streaming carrier replacement preserves the pending image request and ready object URL', async () => {
  const h = harness();
  const pending = deferred();
  let loads = 0;
  let signal;
  const client = {
    owner,
    loadImage(input) {
      loads++;
      signal = input.signal;
      return pending.promise;
    },
  };
  h.render({ client, carriers });
  for (let token = 0; token < 5; token++)
    h.render({
      client,
      carriers: [...carriers, { conversation_id: 'c', content: `token-${token}` }],
    });
  assert.equal(loads, 1);
  assert.equal(signal.aborted, false);
  pending.resolve(new Blob(['image'], { type: 'image/png' }));
  await tick();
  h.render({ client, carriers: [...carriers, { conversation_id: 'c', content: 'final' }] });
  assert.equal(loads, 1);
  assert.equal(h.created.length, 1);
  assert.equal(h.revoked.length, 0);
  h.unmount();
  assert.equal(h.revoked.length, 1);
});

test('new explicit nested owner conflict removes an already ready image without another HTTP request', async () => {
  const h = harness();
  let calls = 0;
  const client = {
    owner,
    async loadImage() {
      calls++;
      return new Blob(['image'], { type: 'image/png' });
    },
  };
  h.render({ client, carriers });
  await tick();
  assert.equal(h.created.length, 1);
  const tree = h.render({ client, carriers: [...carriers, { metadata: { project_id: 'other' } }] });
  assert.match(tree.props.className, /is-unavailable/);
  assert.equal(calls, 1);
  assert.deepEqual(h.revoked, ['blob:preview-0']);
});

test('non-JSON carriers cannot preserve a previous valid request', async () => {
  const h = harness();
  const pending = deferred();
  let signal;
  const client = {
    owner,
    loadImage(input) {
      signal = input.signal;
      return pending.promise;
    },
  };
  h.render({ client, carriers });
  const cycle = {};
  cycle.metadata = cycle;
  h.render({ client, carriers: [...carriers, cycle] });
  assert.equal(signal.aborted, true);
  pending.resolve(new Blob(['image'], { type: 'image/png' }));
  await tick();
  assert.equal(h.created.length, 0);
});

test('late image error after unmount cannot overwrite the released request state', async () => {
  const h = harness();
  const client = { owner, loadImage: async () => new Blob(['image'], { type: 'image/png' }) };
  h.render({ client, carriers });
  await tick();
  const tree = h.render();
  h.unmount();
  tree.props.children.props.onError();
  // Reading the retained hook slots verifies that the escaped DOM callback did
  // not schedule a failed state after cleanup. A real component is unmounted.
  assert.match(h.render().props.className, /is-ready/);
  assert.equal(h.revoked.length, 1);
});
