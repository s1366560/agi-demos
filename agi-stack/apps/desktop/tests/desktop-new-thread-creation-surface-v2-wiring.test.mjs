import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const conversation = source('src/hooks/useAgentConversation.ts');
const threads = source('src/hooks/useConversationThreads.ts');
const authority = source('src/plugins/desktopNewThreadCreationAuthorityModuleV2.ts');

test('new-thread creation resolves every operation through the renderer generation authority', () => {
  assert.match(app, /createDesktopNewThreadCreationOperationsV2/u);
  assert.doesNotMatch(app, /createDesktopNewThreadCreationClientProviderV2/u);
  assert.match(
    app,
    /newThreadCreationClientV2:\s*desktopNewThreadCreationOperationsV2/u,
  );
  assert.match(conversation, /DesktopNewThreadCreationOperationsV2/u);
  assert.match(
    conversation,
    /newThreadCreationClientV2:\s*DesktopNewThreadCreationOperationsV2/u,
  );
  assert.match(threads, /newThreadCreationClientV2/u);
  assert.doesNotMatch(threads, /DesktopApiClient/u);
  assert.doesNotMatch(threads, /new DesktopApiClient\(/u);
});

test('new-thread creation authority exposes only three operations and requires task-flow injection', () => {
  assert.match(
    authority,
    /type DesktopNewThreadCreationMethodV2 =[\s\S]*'createAgentConversation'/u,
  );
  assert.match(authority, /'createTaskSession'[\s\S]*'runAgentMessage'/u);
  for (const method of [
    'createAgentConversation',
    'createTaskSession',
    'runAgentMessage',
  ]) {
    assert.match(authority, new RegExp(`${method}\\(`));
  }
  assert.match(authority, /context\.require<[^>]+>\(\s*'task_flow'/u);
  assert.match(authority, /acquireServiceOperationLease/u);
  assert.match(authority, /bindOperation/u);
  assert.doesNotMatch(
    authority,
    /sendMessage:|createRunInput:|updateAgentConversationMode:/u,
  );
});

test(
  'new-thread hooks bind every operation config without choosing an implementation class',
  () => {
    assert.match(
      threads,
      /newThreadCreationClientV2\.bindOperation\(input\.config\)[\s\S]*\.runAgentMessage/u,
    );
    assert.match(
      threads,
      /newThreadCreationClientV2\.bindOperation\(threadConfig\)[\s\S]*\.createAgentConversation/u,
    );
    assert.match(
      threads,
      /newThreadCreationClientV2\.bindOperation\(threadConfig\)[\s\S]*\.createTaskSession/u,
    );
  },
);
