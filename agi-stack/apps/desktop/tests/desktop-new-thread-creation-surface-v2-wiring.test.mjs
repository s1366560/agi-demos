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
const provider = source('src/features/task/desktopNewThreadCreationClientProviderV2.ts');

test('new-thread creation resolves its API authority from one V2 publication', () => {
  assert.match(app, /createDesktopNewThreadCreationClientProviderV2/u);
  assert.match(
    app,
    /desktopNewThreadCreationClientProviderV2\.publish\(\{ config \}\)/u,
  );
  assert.match(
    app,
    /newThreadCreationClientV2:\s*desktopNewThreadCreationClientV2/u,
  );
  assert.match(conversation, /DesktopNewThreadCreationClientBindingV2/u);
  assert.match(
    conversation,
    /newThreadCreationClientV2:\s*DesktopNewThreadCreationClientBindingV2/u,
  );
  assert.match(threads, /newThreadCreationClientV2/u);
  assert.doesNotMatch(threads, /DesktopApiClient/u);
  assert.doesNotMatch(threads, /new DesktopApiClient\(/u);
});

test('new-thread creation Provider exposes only the three owned transport methods', () => {
  assert.match(
    provider,
    /type DesktopNewThreadCreationMethod =[\s\S]*'createAgentConversation'/u,
  );
  assert.match(provider, /'createTaskSession'[\s\S]*'runAgentMessage'/u);
  for (const method of [
    'createAgentConversation',
    'createTaskSession',
    'runAgentMessage',
  ]) {
    assert.match(provider, new RegExp(`${method}:`));
  }
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(
    provider,
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
