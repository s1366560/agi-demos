import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const root = '/tmp/agistack-desktop-test-dist';

// A focused hook host lets this component exercise async playback and cleanup without media devices.
function audioHost() {
  const hooks = [];
  const created = [];
  const revoked = [];
  let cursor = 0;
  let effects = [];
  let changed = false;
  let mounted = true;
  let props;
  let tree;
  const react = {
    useState(initial) {
      const index = cursor++;
      hooks[index] ??= { value: typeof initial === 'function' ? initial() : initial };
      return [
        hooks[index].value,
        (next) => {
          const value = typeof next === 'function' ? next(hooks[index].value) : next;
          if (mounted && !Object.is(value, hooks[index].value)) {
            hooks[index].value = value;
            changed = true;
          }
        },
      ];
    },
    useRef(initial) {
      const index = cursor++;
      hooks[index] ??= { current: initial };
      return hooks[index];
    },
    useEffect(effect, dependencies) {
      const index = cursor++;
      const previous = hooks[index];
      if (
        !previous ||
        dependencies.some((value, i) => !Object.is(value, previous.dependencies[i]))
      ) {
        hooks[index] = { dependencies, cleanup: previous?.cleanup };
        effects.push(() => {
          hooks[index].cleanup?.();
          hooks[index].cleanup = effect();
        });
      }
    },
  };
  const jsx = (type, props) => ({ type, props });
  const module = { exports: {} };
  const componentRequire = (name) => {
    if (name === 'react') return react;
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx };
    if (name === '../../i18n') return { useI18n: () => ({ t: (key) => key }) };
    throw new Error(`Unexpected audio dependency: ${name}`);
  };
  new Function(
    'require',
    'exports',
    'URL',
    readFileSync(`${root}/src/features/settings/ComputerUseAudio.js`, 'utf8'),
  )(componentRequire, module.exports, {
    createObjectURL(blob) {
      const url = `blob:recording-${created.length + 1}`;
      created.push({ blob, url });
      return url;
    },
    revokeObjectURL: (url) => revoked.push(url),
  });
  const render = (next = props) => {
    props = next;
    cursor = 0;
    changed = false;
    tree = module.exports.ComputerUseAudio(props);
    return tree;
  };
  const flush = () => {
    for (let iteration = 0; iteration < 10; iteration += 1) {
      if (changed) render();
      const current = effects;
      effects = [];
      for (const effect of current) effect();
      if (!changed && !effects.length) return;
    }
    throw new Error('Audio component failed to settle');
  };
  return {
    render,
    flush,
    created,
    revoked,
    element: (type) => tree.props.children.find((child) => child?.type === type),
    unmount() {
      mounted = false;
      for (const hook of hooks) hook.cleanup?.();
    },
  };
}

function audioClient() {
  const requests = [];
  return {
    requests,
    audio: (artifactId, signal) =>
      new Promise((resolve, reject) => requests.push({ artifactId, signal, resolve, reject })),
  };
}

async function resolveAudio(host, request, blob) {
  request.resolve(blob);
  await Promise.resolve();
  await Promise.resolve();
  host.flush();
}

test('playback aborts stale artifact requests and revokes loaded URLs when client scope changes', async () => {
  const host = audioHost();
  const client = audioClient();
  host.render({ client, artifactId: 'cua-audio-a', label: 'First recording' });
  host.flush();
  assert.equal(client.requests.length, 0, 'recording bytes must not download before user playback');
  host.element('button').props.onClick();
  host.flush();
  assert.equal(client.requests[0].artifactId, 'cua-audio-a');

  host.render({ client, artifactId: 'cua-audio-b', label: 'Second recording' });
  host.flush();
  assert.equal(client.requests[0].signal.aborted, true);
  await resolveAudio(host, client.requests[0], new Blob(['late first recording']));
  assert.equal(host.created.length, 0);
  assert.equal(host.element('audio'), undefined);

  host.element('button').props.onClick();
  host.flush();
  const currentBlob = new Blob(['second recording']);
  await resolveAudio(host, client.requests[1], currentBlob);
  assert.deepEqual(host.created, [{ blob: currentBlob, url: 'blob:recording-1' }]);
  assert.equal(host.element('audio').props.src, 'blob:recording-1');

  const nextScope = audioClient();
  host.render({ client: nextScope, artifactId: 'cua-audio-b', label: 'New scope' });
  assert.equal(
    host.element('audio'),
    undefined,
    'old scope audio must disappear before effects run',
  );
  host.flush();
  assert.deepEqual(host.revoked, ['blob:recording-1']);
  host.element('button').props.onClick();
  host.flush();
  host.unmount();
  assert.equal(nextScope.requests[0].signal.aborted, true);
  await resolveAudio(host, nextScope.requests[0], new Blob(['late next scope']));
  assert.equal(
    host.created.length,
    1,
    'an unmounted conversation must not create another Blob URL',
  );
});

test('unmount releases the currently displayed audio Blob URL exactly once', async () => {
  const host = audioHost();
  const client = audioClient();
  host.render({ client, artifactId: 'cua-audio-saved', label: 'Saved recording' });
  host.flush();
  host.element('button').props.onClick();
  await resolveAudio(host, client.requests[0], new Blob(['saved recording']));
  assert.equal(host.element('audio').props.src, 'blob:recording-1');
  host.unmount();
  assert.deepEqual(host.revoked, ['blob:recording-1']);
});
