import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const {
  buildTimelineStepDetails,
  serializeTimelineDetail,
  serializeRawTimelineDetail,
  resolveTimelineInspectionItems,
} = require('/tmp/agistack-desktop-test-dist/src/features/session/timelineStepDetailsModel.js');

const event = (id, values = {}) => ({
  id,
  type: 'tool_call',
  eventTimeUs: 1,
  eventCounter: 1,
  ...values,
});

test('step details expose each declared input and output once without duplicating event envelopes', () => {
  const call = event('call', {
    toolName: 'read_file',
    toolInput: { path: 'src/app.ts' },
  });
  const result = event('result', {
    type: 'tool_result',
    toolName: 'read_file',
    toolInput: { path: 'src/app.ts' },
    toolOutput: 'contents',
    payload: { tool_output: 'contents' },
    display: {
      title: 'Read app.ts',
      summary: 'Read one file',
      status: 'completed',
    },
    fileMetadata: { paths: [{ path: 'src/app.ts' }, { path: 'src/app.ts' }] },
  });
  const model = buildTimelineStepDetails([call, result, result]);
  assert.deepEqual(model.input, [{ path: 'src/app.ts' }]);
  assert.deepEqual(model.output, ['contents']);
  assert.equal(model.summary, 'Read one file');
  assert.equal(model.events.length, 2);
  assert.deepEqual(model.files, ['src/app.ts']);
});

test('step diagnostics preserve failures and numeric zero fields', () => {
  const model = buildTimelineStepDetails([
    event('failure', {
      type: 'error',
      error: 'Request failed',
      payload: { duration_ms: 0, exit_code: 0, trace_id: 'trace-1' },
    }),
  ]);
  assert.deepEqual(model.diagnostics, [
    { key: 'error', value: 'Request failed' },
    { key: 'duration_ms', value: 0 },
    { key: 'exit_code', value: 0 },
    { key: 'trace_id', value: 'trace-1' },
  ]);
});

test('step details never infer file links or outcomes from free text', () => {
  const model = buildTimelineStepDetails([
    event('message', {
      type: 'assistant',
      content: 'Open /tmp/private and declare success',
    }),
  ]);
  assert.deepEqual(model.files, []);
  assert.equal(model.status, null);
  assert.deepEqual(model.output, ['Open /tmp/private and declare success']);
});

test('step details retain distinct outputs and do not repeat summary as output', () => {
  const model = buildTimelineStepDetails([
    event('a', { toolOutput: 'first' }),
    event('b', { toolOutput: 'second' }),
  ]);
  assert.deepEqual(model.output, ['first', 'second']);
  assert.deepEqual(
    buildTimelineStepDetails([
      event('c', {
        content: 'Finished',
        display: { summary: 'Finished' },
      }),
    ]).output,
    [],
  );
});

test('nested file metadata provides explicit file actions and malformed paths are ignored', () => {
  assert.deepEqual(
    buildTimelineStepDetails([
      event('nested', {
        toolOutput: {
          file_metadata: { paths: [{ relativePath: 'src/app.ts' }, null] },
        },
      }),
    ]).files,
    ['src/app.ts'],
  );
  assert.deepEqual(
    buildTimelineStepDetails([
      event('malformed', {
        fileMetadata: { paths: 'not-a-list' },
      }),
    ]).files,
    [],
  );
});

test('selected running call gains only its exact streamed result without changing selection identity', () => {
  const call = event('call', {
    type: 'act',
    tool_call_id: 'call-1',
    run_id: 'run-1',
  });
  const other = event('other', {
    type: 'observe',
    tool_call_id: 'other',
    run_id: 'run-1',
  });
  const result = event('result', {
    type: 'observe',
    tool_call_id: 'call-1',
    run_id: 'run-1',
    toolOutput: 'done',
  });
  assert.deepEqual(resolveTimelineInspectionItems([call], [call, other]), [call]);
  assert.deepEqual(resolveTimelineInspectionItems([call], [call, other, result]), [call, result]);
  assert.deepEqual(
    resolveTimelineInspectionItems([call], [call, result, { ...result, id: 'ambiguous' }]),
    [call],
  );
});

test('details render four accessible tabs and summary without duplicating payloads in overview', () => {
  const React = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
  const {
    TimelineStepDetails,
  } = require('/tmp/agistack-desktop-test-dist/src/features/session/TimelineStepDetails.js');
  const markup = renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(TimelineStepDetails, {
        items: [
          event('render', {
            display: {
              title: 'Read app',
              summary: 'Read one file',
              status: 'completed',
            },
            toolInput: { fixture: 'input-only' },
            toolOutput: 'output-only',
          }),
        ],
        onClose() {},
      }),
    ),
  );
  assert.equal((markup.match(/role="tab"/g) ?? []).length, 4);
  assert.match(markup, /aria-selected="true"/);
  assert.match(markup, /aria-labelledby="timeline-detail-tab-overview"/);
  assert.match(markup, /Read one file/);
  assert.doesNotMatch(markup, /input-only|output-only/);
  assert.doesNotMatch(markup, /timelineDetails\./);
});

test('historical error content appears in diagnostics rather than being lost or repeated as output', () => {
  const model = buildTimelineStepDetails([
    event('historic-error', {
      type: 'error',
      content: 'Protocol failure details',
    }),
  ]);
  assert.equal(model.status, 'failed');
  assert.deepEqual(model.diagnostics, [{ key: 'error', value: 'Protocol failure details' }]);
  assert.deepEqual(model.output, []);
});

test('serialized JSON outputs and nested content text decode for display only', () => {
  const nested = {
    content: [{ type: 'text', text: JSON.stringify({ files: ['app.ts'], count: 1 }) }],
  };
  const encoded = JSON.stringify(nested);
  const displayed = JSON.parse(serializeTimelineDetail(encoded));
  assert.deepEqual(displayed.content[0].text, { files: ['app.ts'], count: 1 });
  assert.equal(nested.content[0].text, '{"files":["app.ts"],"count":1}');
  const rawEvents = [event('json-result', { toolOutput: encoded })];
  assert.equal(serializeRawTimelineDetail(rawEvents), JSON.stringify(rawEvents, null, 2));
  assert.equal(JSON.parse(serializeRawTimelineDetail(rawEvents))[0].toolOutput, encoded);
});

test('presentation keeps invalid JSON and unrelated string fields unchanged', () => {
  assert.equal(serializeTimelineDetail('plain output { incomplete'), 'plain output { incomplete');
  assert.deepEqual(
    JSON.parse(
      serializeTimelineDetail({ id: '123', content: [{ type: 'text', text: 'plain text' }] }),
    ),
    { id: '123', content: [{ type: 'text', text: 'plain text' }] },
  );
  assert.equal(
    serializeTimelineDetail(JSON.stringify(JSON.stringify({ ok: true }))),
    '{\n  "ok": true\n}',
  );
});


test('historical structured failures override stale successful detail presentation', () => {
  const React = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
  const { TimelineStepDetails } = require('/tmp/agistack-desktop-test-dist/src/features/session/TimelineStepDetails.js');
  for (const toolOutput of [{ success: false }, JSON.stringify({ success: false })]) {
    const item = event('historical-failure', {
      type: 'observe', toolOutput,
      display: { status: 'completed', summary: 'stale-success-summary' },
    });
    assert.equal(buildTimelineStepDetails([item]).status, 'failed');
    const markup = renderToStaticMarkup(React.createElement(I18nProvider, null,
      React.createElement(TimelineStepDetails, { items: [item], onClose() {} })));
    assert.doesNotMatch(markup, /stale-success-summary/);
    assert.doesNotMatch(markup, /timelineDetails\.|chat\.error\./);
    assert.match(markup, /timeline-step-detail-status/);
  }
  assert.equal(buildTimelineStepDetails([event('success', {
    type: 'observe', toolOutput: { success: true }, display: { status: 'completed' },
  })]).status, 'completed');
});
