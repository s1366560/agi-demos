import { randomUUID } from 'node:crypto';
import { mkdir, unlink, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const maxBytes = 64 * 1_048_576;

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/** The renderer can supply package bytes. Only Main can name a native transfer file. */
export async function invokeDevicePlugin(
  root: string,
  args: unknown,
  invoke: (args: Record<string, unknown>) => Promise<unknown>,
) {
  if (!record(args) || !record(args.input) || !record(args.input.operation)) {
    throw new Error('device_plugin_request_invalid');
  }
  const operation = args.input.operation;
  if (Object.hasOwn(operation, 'archive_id')) throw new Error('device_plugin_request_invalid');
  if (operation.action !== 'inspect' && operation.action !== 'install') {
    if (Buffer.byteLength(JSON.stringify(args)) > 256 * 1024) {
      throw new Error('device_plugin_request_too_large');
    }
    return invoke(args);
  }
  const { archive_base64: base64, ...fields } = operation;
  const archiveId = randomUUID();
  const request = { input: { ...args.input, operation: { ...fields, archive_id: archiveId } } };
  if (
    typeof base64 !== 'string' ||
    base64.length > Math.ceil(maxBytes / 3) * 4 ||
    Buffer.byteLength(JSON.stringify(request)) > 256 * 1024
  ) {
    throw new Error('device_plugin_request_too_large');
  }
  const bytes = Buffer.from(base64, 'base64');
  if (!bytes.length || bytes.length > maxBytes) throw new Error('device_plugin_archive_invalid');
  const spool = join(root, 'device-plugin-transfers');
  await mkdir(spool, { recursive: true, mode: 0o700 });
  const path = join(spool, archiveId);
  await writeFile(path, bytes, { mode: 0o600, flag: 'wx' });
  try {
    return await invoke(request);
  } finally {
    await unlink(path).catch((error: NodeJS.ErrnoException) => {
      if (error.code !== 'ENOENT') throw error;
    });
  }
}
