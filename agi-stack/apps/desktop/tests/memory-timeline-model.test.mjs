import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  memoryCapturePresentation,
  isMemoryTimelineEvent,
  memoryPinStorageKey,
  memoryRecallPresentation,
  parseMemoryPinState,
  serializeMemoryPinState,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/memoryTimelineModel.js');

const memoryTimelineCardsSource = readFileSync(
  new URL('../src/features/chat/MemoryTimelineCards.tsx', import.meta.url),
  'utf8',
);
const chatTimelineSource = readFileSync(
  new URL('../src/features/chat/ChatTimeline.tsx', import.meta.url),
  'utf8',
);
const sessionSteeringQaSource = readFileSync(
  new URL('../src/qa/SessionSteeringQa.tsx', import.meta.url),
  'utf8',
);
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');

test('memory recall presentation preserves inspectable retrieval evidence', () => {
  assert.deepEqual(
    memoryRecallPresentation({
      id: 'memory-recalled-1',
      type: 'memory_recalled',
      eventTimeUs: 1,
      eventCounter: 1,
      payload: {
        memories: [
          {
            id: 'memory-preference',
            content: 'Prefer concise release notes with explicit verification evidence.',
            score: 0.93,
            source: 'project',
            category: 'preference',
          },
          {
            content: 'Run the native desktop client through the canonical Make target.',
            score: 0.87,
            source: 'repository',
            category: 'procedural',
          },
          { content: 'Discard malformed scores.', score: 'high', source: 'project' },
          { score: 0.5, source: 'project', category: 'invalid-without-content' },
        ],
        count: 3,
        search_ms: 24,
      },
    }),
    {
      count: 3,
      searchMs: 24,
      memories: [
        {
          key: 'memory-preference',
          content: 'Prefer concise release notes with explicit verification evidence.',
          score: 0.93,
          source: 'project',
          category: 'preference',
          originalIndex: 0,
        },
        {
          key: 'memory-recalled-1:1',
          content: 'Run the native desktop client through the canonical Make target.',
          score: 0.87,
          source: 'repository',
          category: 'procedural',
          originalIndex: 1,
        },
        {
          key: 'memory-recalled-1:2',
          content: 'Discard malformed scores.',
          score: null,
          source: 'project',
          category: '',
          originalIndex: 2,
        },
      ],
      sources: [
        { source: 'project', count: 2 },
        { source: 'repository', count: 1 },
      ],
    },
  );
});

test(
  'memory recall presentation accepts camel-case live fields and rejects unrelated events',
  () => {
    assert.deepEqual(
      memoryRecallPresentation({
        id: 'memory-recalled-live',
        type: 'memory_recalled',
        eventTimeUs: 2,
        eventCounter: 2,
        memories: [
          {
            content: 'Live event memory',
            score: 0.78,
            source: 'conversation',
            category: 'semantic',
          },
        ],
        searchMs: 9,
      }),
      {
        count: 1,
        searchMs: 9,
        memories: [
          {
            key: 'memory-recalled-live:0',
            content: 'Live event memory',
            score: 0.78,
            source: 'conversation',
            category: 'semantic',
            originalIndex: 0,
          },
        ],
        sources: [{ source: 'conversation', count: 1 }],
      },
    );
    assert.equal(
      memoryRecallPresentation({
        id: 'thought-1',
        type: 'thought',
        eventTimeUs: 3,
        eventCounter: 3,
      }),
      null,
    );
  },
);

test('memory capture presentation normalizes count and categories', () => {
  assert.deepEqual(
    memoryCapturePresentation({
      id: 'memory-captured-1',
      type: 'memory_captured',
      eventTimeUs: 4,
      eventCounter: 4,
      payload: {
        captured_count: 2,
        categories: ['semantic', '', 'preference', 42],
      },
    }),
    { count: 2, categories: ['semantic', 'preference'] },
  );
  assert.equal(
    memoryCapturePresentation({
      id: 'memory-captured-empty',
      type: 'memory_captured',
      eventTimeUs: 5,
      eventCounter: 5,
      capturedCount: 0,
      categories: [],
    }),
    null,
  );
});

test('memory pin persistence is versioned, scoped, deterministic, and fail-closed', () => {
  assert.equal(
    memoryPinStorageKey('conversation/with spaces'),
    'agistack.desktop.memory-pins.v1:conversation%2Fwith%20spaces',
  );
  assert.equal(memoryPinStorageKey(null), 'agistack.desktop.memory-pins.v1:unscoped');
  assert.deepEqual(
    parseMemoryPinState('["memory-b","memory-a","memory-b",42,""]'),
    new Set(['memory-b', 'memory-a']),
  );
  assert.deepEqual(parseMemoryPinState('{"memory-a":true}'), new Set());
  assert.deepEqual(parseMemoryPinState('not-json'), new Set());
  assert.equal(
    serializeMemoryPinState(new Set(['memory-b', 'memory-a'])),
    '["memory-a","memory-b"]',
  );
});

test('memory timeline event detection is structural and exact', () => {
  assert.equal(
    isMemoryTimelineEvent({
      id: 'memory-recalled-2',
      type: 'memory_recalled',
      eventTimeUs: 6,
      eventCounter: 6,
    }),
    true,
  );
  assert.equal(
    isMemoryTimelineEvent({
      id: 'memory-captured-2',
      type: 'memory_captured',
      eventTimeUs: 7,
      eventCounter: 7,
    }),
    true,
  );
  assert.equal(
    isMemoryTimelineEvent({
      id: 'memory-like-text',
      type: 'thought',
      eventTimeUs: 8,
      eventCounter: 8,
      content: 'memory_recalled',
    }),
    false,
  );
});

test('Desktop promotes memory events into inspectable first-class timeline cards', () => {
  assert.match(chatTimelineSource, /isMemoryTimelineEvent\(node\.item\)/);
  assert.match(chatTimelineSource, /<MemoryTimelineEvent/);
  assert.match(memoryTimelineCardsSource, /className="memory-recall-card/);
  assert.match(memoryTimelineCardsSource, /memoryPinStorageKey/);
  assert.match(memoryTimelineCardsSource, /navigator\.clipboard\.writeText/);
  assert.match(memoryTimelineCardsSource, /setActiveSource/);
  assert.match(memoryTimelineCardsSource, /memory-captured-card/);
  assert.match(sessionSteeringQaSource, /memory-events/);
  assert.equal(
    i18nSource.split("'chat.memoryRecalledCount'").length - 1,
    2,
    'memory recall labels must cover both locales',
  );
});
