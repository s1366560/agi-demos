import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
const require = createRequire(import.meta.url);
const baseSource = readFileSync('agi-stack/apps/desktop/tests/session-projection-model.test.mjs', 'utf8');
const start = baseSource.indexOf('function validCloudProjection()');
const end = baseSource.indexOf('\ntest(', start);
const base = vm.runInNewContext(`${baseSource.slice(start, end)}\nvalidCloudProjection()`);
const { decodeConversationSessionProjection } = require('/tmp/runtime-hydration-desktop-dist/apps/desktop/src/features/session/sessionProjectionModel.js');
const { validateApprovalRequest } = require('/tmp/runtime-hydration-desktop-dist/apps/desktop/src/features/session/sessionDecisionModel.js');
for (const file of process.argv.slice(2)) {
  const request = JSON.parse(readFileSync(file, 'utf8'));
  const scope = base.conversation.id;
  // All scope identifiers belong to the in-memory test; align the enclosing fixture.
  request.conversation_id = scope;
  base.pending_hitl = [request];
  const decoded = decodeConversationSessionProjection(base, scope);
  assert.ok(decoded, 'Actual persisted permission must decode');
  assert.equal(validateApprovalRequest(decoded.pendingHitl[0]).canApprove, true);
  const { permission, ...withoutPermission } = request;
  base.pending_hitl = [withoutPermission];
  const incomplete = decodeConversationSessionProjection(base, scope);
  assert.equal(validateApprovalRequest(incomplete.pendingHitl[0]).canApprove, false);
  console.log(`PASS persisted ${file.split('/').at(-2)}: approve once enabled; missing context remains disabled`);
}
