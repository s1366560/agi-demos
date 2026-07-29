import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const {
  clampPanelWidth,
  panelWidthFromDrag,
  panelWidthFromKey,
  parsePersistedPanelWidth,
} = require('/tmp/agistack-desktop-test-dist/src/components/resizeHandleModel.js');
const { ResizeHandle } = require('/tmp/agistack-desktop-test-dist/src/components/ResizeHandle.js');

const resizeHandleSource = readFileSync(
  new URL('../src/components/ResizeHandle.tsx', import.meta.url),
  'utf8',
);

const constraints = { min: 180, max: 420, default: 220 };

test('panel width clamps to the configured constraints', () => {
  assert.equal(clampPanelWidth(100, constraints), 180);
  assert.equal(clampPanelWidth(500, constraints), 420);
  assert.equal(clampPanelWidth(260.4, constraints), 260.4);
  assert.equal(clampPanelWidth(Number.NaN, constraints), 220);
});

test('persisted panel width accepts finite values and clamps drift', () => {
  assert.equal(parsePersistedPanelWidth('260', constraints), 260);
  assert.equal(parsePersistedPanelWidth('999', constraints), 420);
  assert.equal(parsePersistedPanelWidth('12', constraints), 180);
  assert.equal(parsePersistedPanelWidth('abc', constraints), null);
  assert.equal(parsePersistedPanelWidth(null, constraints), null);
  assert.equal(parsePersistedPanelWidth(undefined, constraints), null);
});

test('drag grows a trailing-edge panel rightward and a leading-edge panel leftward', () => {
  assert.equal(panelWidthFromDrag(220, 40, 'trailing', constraints), 260);
  assert.equal(panelWidthFromDrag(220, -40, 'trailing', constraints), 180);
  assert.equal(panelWidthFromDrag(220, -40, 'leading', constraints), 260);
  assert.equal(panelWidthFromDrag(220, 40, 'leading', constraints), 180);
  assert.equal(panelWidthFromDrag(220, 500, 'trailing', constraints), 420);
  assert.equal(panelWidthFromDrag(220, 500, 'leading', constraints), 180);
});

test('keyboard arrows resize in the drag direction and ignore other keys', () => {
  assert.equal(panelWidthFromKey(220, 'ArrowRight', 'trailing', constraints), 236);
  assert.equal(panelWidthFromKey(220, 'ArrowLeft', 'trailing', constraints), 204);
  assert.equal(panelWidthFromKey(220, 'ArrowRight', 'leading', constraints), 204);
  assert.equal(panelWidthFromKey(220, 'ArrowLeft', 'leading', constraints), 236);
  assert.equal(panelWidthFromKey(410, 'ArrowRight', 'trailing', constraints), 420);
  assert.equal(panelWidthFromKey(220, 'ArrowDown', 'trailing', constraints), null);
  assert.equal(panelWidthFromKey(220, 'Enter', 'leading', constraints), null);
});

test('drag teardown always restores the global cursor and selection', () => {
  // Window-level listeners keep tracking the pointer beyond the handle bounds.
  assert.match(resizeHandleSource, /window\.addEventListener\('pointermove'/);
  assert.match(resizeHandleSource, /window\.addEventListener\('pointerup'/);
  assert.match(resizeHandleSource, /window\.addEventListener\('pointercancel'/);
  // Implicit capture loss, window blur, and Escape all end the drag.
  assert.match(resizeHandleSource, /window\.addEventListener\('lostpointercapture'/);
  assert.match(resizeHandleSource, /window\.addEventListener\('blur'/);
  assert.match(resizeHandleSource, /event\.key !== 'Escape'/);
  // The effect cleanup restores globals even when the handle unmounts mid-drag.
  assert.match(resizeHandleSource, /return \(\) => \{[\s\S]*document\.body\.style\.cursor = ''/);
});

test('resize handle renders an accessible vertical separator', () => {
  const markup = renderToStaticMarkup(
    React.createElement(ResizeHandle, {
      side: 'trailing',
      width: 260,
      constraints,
      label: 'Resize sidebar',
      onResize: () => {},
      onReset: () => {},
    }),
  );

  assert.match(markup, /role="separator"/);
  assert.match(markup, /aria-orientation="vertical"/);
  assert.match(markup, /aria-valuenow="260"/);
  assert.match(markup, /aria-valuemin="180"/);
  assert.match(markup, /aria-valuemax="420"/);
  assert.match(markup, /aria-label="Resize sidebar"/);
  assert.match(markup, /tabindex="0"/i);
  assert.match(markup, /panel-resize-handle-trailing/);
});
