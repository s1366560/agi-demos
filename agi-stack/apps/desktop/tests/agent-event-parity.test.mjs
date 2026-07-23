import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { test } from 'node:test';

const backendTypesSource = readFileSync(
  new URL('../../../../src/domain/events/types.py', import.meta.url),
  'utf8',
);
const webRouterSource = readFileSync(
  new URL('../../../../web/src/services/agent/messageRouter.ts', import.meta.url),
  'utf8',
);
const desktopSourceRoot = new URL('../src/', import.meta.url);

const agentEventTypeBlock = backendTypesSource.slice(
  backendTypesSource.indexOf('class AgentEventType'),
  backendTypesSource.indexOf('# Event Type Utilities'),
);
const backendEventTypes = [
  ...agentEventTypeBlock.matchAll(/^\s+[A-Z][A-Z0-9_]*\s*=\s*"([^"]+)"/gm),
].map((match) => match[1]);
const webRoutedEventTypes = [...webRouterSource.matchAll(/case '([^']+)'/g)].map(
  (match) => match[1],
);

const eventHandlingFiles = readdirSync(desktopSourceRoot, { recursive: true })
  .filter((entry) => typeof entry === 'string' && /\.(ts|tsx)$/.test(entry))
  .filter(
    (entry) =>
      entry === 'App.tsx' ||
      entry === 'hooks/useAgentSocket.ts' ||
      entry.startsWith('features/chat/') ||
      entry.startsWith('features/session/') ||
      /^features\/workspace\/.*EventModel\.ts$/.test(entry) ||
      /^features\/settings\/.*EventModel\.ts$/.test(entry),
  );
const desktopEventHandlingSource = eventHandlingFiles
  .map((entry) => readFileSync(new URL(entry, desktopSourceRoot), 'utf8'))
  .join('\n');

test('Desktop event handling covers every backend and Web Agent event contract', () => {
  const expectedEventTypes = new Set([...backendEventTypes, ...webRoutedEventTypes]);
  const missingEventTypes = [...expectedEventTypes].filter(
    (eventType) => !desktopEventHandlingSource.includes(eventType),
  );

  assert.deepEqual(missingEventTypes, []);
});
