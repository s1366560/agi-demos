import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(
  new URL('../src/qa/CloudSessionQueueQa.tsx', import.meta.url),
  'utf8',
);

test('cloud session QA exercises the production socket queue before opening realtime', () => {
  assert.match(source, /QA_AGENT_SOCKET_GENERATION_LEASE_V2/u);
  assert.match(source, /kind: 'generation'/u);
  assert.match(source, /digest: 'sha256:qa-cloud-session-generation-v2'/u);
  assert.match(
    source,
    new RegExp(
      String.raw`useAgentSocket\([\s\S]+?'conversation-cloud',` +
        String.raw`[\s\S]+?QA_AGENT_SOCKET_GENERATION_LEASE_V2[\s\S]+?\)`,
      'u',
    ),
  );
  assert.match(source, /socket\.sendAgentMessage\(\{/);
  assert.match(source, /workspaceId: 'workspace-created-for-session'/);
  assert.match(source, /QaWebSocket\.latest\?\.open\(\)/);
  assert.match(source, /messageId: 'message-cloud-1'/);
  assert.match(source, /agentId: 'definition-reviewer'/);
  assert.match(source, /forcedSkillName: 'source-research'/);
  assert.match(source, /data-qa-context/);
  assert.match(source, /fileMetadata:/);
  assert.match(source, /data-qa-attachment/);
});
