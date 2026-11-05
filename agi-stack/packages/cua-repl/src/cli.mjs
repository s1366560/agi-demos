import { createInterface } from 'node:readline';
import { randomUUID } from 'node:crypto';
import { ReplKernel } from './kernel.mjs';
import { resultPreview } from './result-preview.mjs';

const MAX_FRAME_BYTES = 16 * 1024 * 1024;
const write = process.stdout.write.bind(process.stdout);
const send = message => {
  const frame = JSON.stringify(message, (_key, value) => typeof value === 'bigint' ? `${value}n` : value);
  if (Buffer.byteLength(frame) > MAX_FRAME_BYTES) throw new Error('output frame exceeds 16 MiB');
  write(`${frame}\n`);
};
const pending = new Map();
const rpc = (method, params, executionId) => new Promise((resolve, reject) => {
  const id = randomUUID();
  pending.set(id, { resolve, reject });
  send({ type: 'rpc', id, executionId, method, params });
});
let kernel;
let busy = false;
const errorValue = error => ({ name: error.name ?? 'Error', message: error.message ?? String(error), ...(error.code ? { code: error.code } : {}) });

async function handle(message) {
  if (!message || typeof message !== 'object') throw new TypeError('frame must be an object');
  if (message.type === 'rpc_response') {
    const request = pending.get(message.id);
    if (!request) throw new Error('RPC response does not match an active request');
    pending.delete(message.id);
    if (message.error) request.reject(Object.assign(new Error(message.error.message), { code: message.error.code }));
    else request.resolve(message.result);
    return;
  }
  if (typeof message.id !== 'string' || !message.id) throw new TypeError('request id must be a non-empty string');
  if (busy) throw new Error('an execution is already active');
  busy = true;
  try {
    if (!kernel) kernel = new ReplKernel({ send, rpc, ...message.context });
    let value;
    if (message.type === 'execute') value = await kernel.execute(message.id, message.code, message.context);
    else if (message.type === 'reset') value = kernel.reset();
    else if (message.type === 'add_module_dir') value = await kernel.addModuleDirectory(message.path);
    else throw new TypeError('unknown request type');
    send({ type: 'result', id: message.id, ok: true, ...(value === undefined ? {} : { value: resultPreview(value) }) });
  } catch (error) { send({ type: 'result', id: message.id, ok: false, error: errorValue(error) }); }
  finally { busy = false; }
}

createInterface({ input: process.stdin, crlfDelay: Infinity }).on('line', line => {
  let message;
  try {
    if (Buffer.byteLength(line) > MAX_FRAME_BYTES) throw new Error('input frame exceeds 16 MiB');
    message = JSON.parse(line);
    void handle(message).catch(error => send({ type: 'result', id: message?.id ?? null, ok: false, error: errorValue(error) }));
  } catch (error) { send({ type: 'result', id: message?.id ?? null, ok: false, error: errorValue(error) }); }
}).on('close', () => {
  for (const request of pending.values()) request.reject(new Error('host transport closed'));
  pending.clear();
  process.exit(0);
});
send({ type: 'ready', protocolVersion: 1 });
