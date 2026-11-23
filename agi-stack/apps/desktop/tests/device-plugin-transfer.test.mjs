import assert from 'node:assert/strict';
import { mkdtemp, readFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import { invokeDevicePlugin } from '../electron/main/devicePluginTransfer.ts';

test('signed archives use a host-selected private transfer and are cleaned up on rejection', async () => {
  const root = await mkdtemp(join(tmpdir(), 'device-plugin-transfer-'));
  const bytes = Buffer.alloc(4 * 1024 * 1024, 42);
  const args = {
    input: { operation: { action: 'inspect', archive_base64: bytes.toString('base64') } },
  };
  try {
    await assert.rejects(
      invokeDevicePlugin(root, args, async ({ input }) => {
        assert.equal('archive_base64' in input.operation, false);
        assert.deepEqual(
          await readFile(join(root, 'device-plugin-transfers', input.operation.archive_id)),
          bytes,
        );
        throw Error('verification failed');
      }),
      /verification failed/,
    );
    assert.deepEqual(await readdir(join(root, 'device-plugin-transfers')), []);
    await assert.rejects(
      invokeDevicePlugin(
        root,
        { input: { operation: { action: 'inspect', archive_id: 'replacement' } } },
        () => assert.fail(),
      ),
      /request_invalid/,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
