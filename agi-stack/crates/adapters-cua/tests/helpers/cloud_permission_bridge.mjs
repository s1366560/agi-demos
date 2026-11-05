// Compile the current production bridge in memory; never open an actual socket.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { join } from 'node:path';

const repository = process.argv[2];
const desktop = join(repository, 'agi-stack/apps/desktop');
const require = createRequire(join(desktop, 'package.json'));
const ts = require('typescript');
const path = join(desktop, 'electron/main/computerUseCloudDeviceBridge.ts');
const source = await readFile(path, 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText;
const compiledModule = { exports: {} };
new Function('module', 'exports', 'require', compiled)(
  compiledModule,
  compiledModule.exports,
  require
);
const { createComputerUseCloudDeviceBridge } = compiledModule.exports;
let input = '';
for await (const chunk of process.stdin) input += chunk;
const { envelope, requestId } = JSON.parse(input);
const scope = {
  tenant_id: 'fixture-tenant',
  project_id: 'fixture-project',
  workspace_id: null,
  conversation_id: 'fixture-conversation',
};
let resolve;
const result = new Promise((done) => {
  resolve = done;
});
const send = async (message) => {
  if (message.type === 'computer_use_result') resolve(message);
};
const bridge = createComputerUseCloudDeviceBridge(async (command, args) => {
  assert.equal(command, 'computer_use_cloud_v2');
  assert.equal(args.input.connection_id, 'fixture-connection');
  assert.deepEqual(args.input.scope, scope);
  switch (args.input.action) {
    case 'describe':
      return { device_id: 'fixture-device', tool_definitions: [], scope, revision: 7 };
    case 'call':
      assert.equal(args.input.request_id, requestId);
      return envelope;
    case 'close':
      return { closed: true };
    default:
      throw new Error('unexpected fixture operation');
  }
});
let timer;
try {
  await bridge.opened('fixture-connection', scope, send);
  assert.equal(
    bridge.receive(
      'fixture-connection',
      scope,
      JSON.stringify({ type: 'computer_use_request', request_id: requestId }),
      send
    ),
    true
  );
  const forwarded = await Promise.race([
    result,
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('bridge fixture timeout')), 5000);
    }),
  ]);
  process.stdout.write(JSON.stringify(forwarded));
} finally {
  clearTimeout(timer);
  bridge.closed('fixture-connection', scope);
}
