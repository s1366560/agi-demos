import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ReplKernel } from '../src/kernel.mjs';

const signatures = [
  ['image/png', Buffer.from('89504e470d0a1a0a', 'hex')],
  ['image/jpeg', Buffer.from('ffd8ffe000104a464946', 'hex')],
  ['image/webp', Buffer.from('524946461000000057454250', 'hex')],
];

test('bare image buffers declare their encoded format for every supported byte container', async () => {
  for (const [mimeType, bytes] of signatures) {
    for (const container of ['uint8', 'arraybuffer', 'buffer', 'base64']) {
      const output = [];
      const repl = new ReplKernel({ send: value => output.push(value), rpc() { throw new Error('unexpected RPC'); } });
      const encoded = JSON.stringify(bytes.toString('base64'));
      const expression = {
        uint8: `Uint8Array.from(Buffer.from(${encoded}, 'base64'))`,
        arraybuffer: `Uint8Array.from(Buffer.from(${encoded}, 'base64')).buffer`,
        buffer: `Buffer.from(${encoded}, 'base64')`,
        base64: encoded,
      }[container];
      await repl.execute('image', `nodeRepl.emitImage(${expression});`);
      assert.deepEqual(output, [{ type: 'output', id: 'image', content: { type: 'image', mimeType, data: bytes.toString('base64') } }]);
    }
  }
});

test('unknown bare image bytes fail before output and explicit declarations remain host validated', async () => {
  const output = [];
  const repl = new ReplKernel({ send: value => output.push(value), rpc() { throw new Error('unexpected RPC'); } });
  await assert.rejects(repl.execute('unknown', 'nodeRepl.emitImage(new Uint8Array([1,2,3]));'), /image format/);
  await assert.rejects(repl.execute('invalid-header', 'nodeRepl.emitImage(Buffer.from("d2c9c6c61000000057454250", "hex"));'), /image format/);
  assert.deepEqual(output, []);
  await repl.execute('declared', 'nodeRepl.emitImage({bytes:Buffer.from([255,216,255]),mimeType:"image/png"});');
  assert.equal(output[0].content.mimeType, 'image/png');
});

test('public browser screenshot bytes retain JPEG encoding through the bare emitImage API', async () => {
  const output = [];
  const jpeg = signatures[1][1].toString('base64');
  const repl = new ReplKernel({
    send: value => output.push(value), enabledSurfaces: ['browser'],
    rpc: async (method, params) => {
      assert.equal(method, 'browser.operation');
      if (params.operation === 'browsers.list') return [{ id: 'chrome', type: 'chrome' }];
      if (params.operation === 'tabs.list') return { tabs: [{ id: '7', title: 'Owned fixture', url: 'https://fixture.test/' }] };
      if (params.operation === 'tab.claim') return {};
      if (params.operation === 'ax.get') return 'Owned fixture';
      if (params.operation === 'tab.screenshot') return { mimeType: 'image/jpeg', dataBase64: jpeg, width: 1, height: 1 };
      throw new Error(`unexpected operation ${params.operation}`);
    },
  });
  await repl.execute('bind', 'var qaTab = await cua.getTab("7", {browser:"chrome"});');
  await repl.execute('capture', 'var qaScreenshot = await qaTab.screenshot(); nodeRepl.emitImage(qaScreenshot);');
  const media = output.filter(value => value.content.type === 'image');
  assert.deepEqual(media, [{ type: 'output', id: 'capture', content: { type: 'image', mimeType: 'image/jpeg', data: jpeg } }]);
});
