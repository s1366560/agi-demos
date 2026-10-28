import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const module = { exports: {} };
new Function(
  'module',
  'exports',
  ts.transpileModule(
    readFileSync(new URL('../src/features/chat/mcpAppGuestLayout.ts', import.meta.url), 'utf8'),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } },
  ).outputText,
)(module, module.exports);
const { computeMcpAppGuestBounds, intersectGuestRects } = module.exports;
const viewport = { x: 0, y: 0, width: 1000, height: 800 };

function assertContained(inner, outer) {
  assert.ok(inner.x >= outer.x);
  assert.ok(inner.y >= outer.y);
  assert.ok(inner.x + inner.width <= outer.x + outer.width);
  assert.ok(inner.y + inner.height <= outer.y + outer.height);
}

function assertExcludesWithGutter(result, blocker) {
  assert.equal(
    intersectGuestRects(result, {
      x: blocker.x - 8,
      y: blocker.y - 8,
      width: blocker.width + 16,
      height: blocker.height + 16,
    }),
    null,
  );
}

test('guest bounds intersect the slot and viewport without mutating either', () => {
  const slot = Object.freeze({ x: -50, y: 100, width: 1200, height: 900 });
  assert.deepEqual(computeMcpAppGuestBounds(slot, Object.freeze(viewport), []), {
    x: 0,
    y: 100,
    width: 1000,
    height: 700,
  });
  assert.equal(intersectGuestRects(viewport, { x: 1000, y: 0, width: 10, height: 10 }), null);
});

test('top right safety controls leave the largest available rectangular guest area', () => {
  const blocker = { x: 700, y: 50, width: 280, height: 220 };
  const result = computeMcpAppGuestBounds(viewport, viewport, [blocker]);
  assert.deepEqual(result, { x: 0, y: 0, width: 692, height: 800 });
  assertExcludesWithGutter(result, blocker);
});

test('every reserved popup is excluded, including overlapping and repeated rectangles', () => {
  const blockers = [
    { x: 650, y: 80, width: 330, height: 180 },
    { x: 630, y: 170, width: 300, height: 250 },
    { x: 650, y: 80, width: 330, height: 180 },
    { x: 50, y: 500, width: 350, height: 200 },
  ];
  const result = computeMcpAppGuestBounds(viewport, viewport, blockers);
  assert.ok(result);
  assertContained(result, viewport);
  for (const blocker of blockers) assertExcludesWithGutter(result, blocker);
  assert.deepEqual(
    computeMcpAppGuestBounds(viewport, viewport, blockers.slice().reverse()),
    result,
  );
});

test('fractional scroll positions round inward and preserve the safety gutter', () => {
  const slot = { x: 10.2, y: 12.6, width: 430.7, height: 333.9 };
  const blocker = { x: 300.3, y: 35.2, width: 130.9, height: 60.3 };
  const result = computeMcpAppGuestBounds(slot, viewport, [blocker]);
  assert.ok(result);
  assertContained(result, slot);
  assertExcludesWithGutter(result, blocker);
  for (const value of Object.values(result)) assert.equal(Number.isInteger(value), true);
});

test('covered, offscreen, zero-area and invalid geometry produce no native child view', () => {
  assert.equal(computeMcpAppGuestBounds(viewport, viewport, [viewport]), null);
  assert.equal(
    computeMcpAppGuestBounds({ x: 2000, y: 0, width: 10, height: 10 }, viewport, []),
    null,
  );
  for (const field of ['x', 'y', 'width', 'height']) {
    for (const invalid of [NaN, Infinity, -Infinity]) {
      assert.equal(computeMcpAppGuestBounds({ ...viewport, [field]: invalid }, viewport, []), null);
      assert.equal(
        computeMcpAppGuestBounds(viewport, viewport, [{ ...viewport, [field]: invalid }]),
        null,
      );
    }
  }
  for (const size of [0, -1]) {
    assert.equal(computeMcpAppGuestBounds({ ...viewport, width: size }, viewport, []), null);
    assert.equal(computeMcpAppGuestBounds(viewport, { ...viewport, height: size }, []), null);
  }
});

test('occluder cardinality is bounded and fails closed before rectangle expansion', () => {
  const outside = { x: 2000, y: 2000, width: 2, height: 2 };
  assert.deepEqual(computeMcpAppGuestBounds(viewport, viewport, Array(64).fill(outside)), viewport);
  assert.equal(computeMcpAppGuestBounds(viewport, viewport, Array(65).fill(outside)), null);
});

test('deterministic geometry samples never overlap any reserved control', () => {
  let seed = 0x43a82719;
  const random = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 0x100000000;
  };
  for (let sample = 0; sample < 80; sample += 1) {
    const slot = {
      x: random() * 300 - 100,
      y: random() * 200 - 100,
      width: random() * 900 + 1,
      height: random() * 700 + 1,
    };
    const blockers = Array.from({ length: 12 }, () => ({
      x: random() * 1100 - 50,
      y: random() * 900 - 50,
      width: random() * 200 + 1,
      height: random() * 180 + 1,
    }));
    const result = computeMcpAppGuestBounds(slot, viewport, blockers);
    if (!result) continue;
    assertContained(result, slot);
    assertContained(result, viewport);
    for (const blocker of blockers) assertExcludesWithGutter(result, blocker);
  }
});
