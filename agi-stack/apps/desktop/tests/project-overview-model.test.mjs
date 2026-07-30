import assert from 'node:assert/strict';
import test from 'node:test';

import {
  beginProjectOverviewRequest,
  completeProjectOverviewRequest,
  emptyProjectOverviewState,
  failProjectOverviewRequest,
  projectOverviewRequestIsCurrent,
  retryProjectOverviewRequest,
} from '/tmp/agistack-desktop-test-dist/src/features/project/projectOverviewModel.js';

const scope = {
  authority: 'cloud',
  tenantId: 'tenant-1',
  projectId: 'project-1',
};
const otherScope = {
  authority: 'cloud',
  tenantId: 'tenant-1',
  projectId: 'project-2',
};

function readyResult() {
  return {
    kind: 'ready',
    snapshot: {
      scope,
      project: {
        id: 'project-1',
        tenant_id: 'tenant-1',
        name: 'Desktop parity',
        description: null,
        created_at: null,
        updated_at: null,
      },
      stats: {
        memory_count: 0,
        storage_used: 0,
        storage_limit: 0,
        active_nodes: 0,
        collaborators: 0,
      },
      latestMemories: [],
      latestMemoriesTotal: 0,
    },
  };
}

test('project overview represents idle, loading, ready, and empty states', () => {
  const idle = emptyProjectOverviewState();
  assert.deepEqual(idle, {
    status: 'idle',
    scope: null,
    request: null,
    snapshot: null,
    error: null,
    retry: null,
  });

  const request = { scope, requestId: 1 };
  const loading = beginProjectOverviewRequest(request);
  assert.deepEqual(loading, {
    status: 'loading',
    scope,
    request,
    snapshot: null,
    error: null,
    retry: null,
  });

  const ready = completeProjectOverviewRequest(loading, request, readyResult());
  assert.equal(ready.status, 'ready');
  assert.deepEqual(ready.snapshot, readyResult().snapshot);
  assert.equal(ready.retry, null);

  const emptyRequest = { scope, requestId: 2 };
  const empty = completeProjectOverviewRequest(
    beginProjectOverviewRequest(emptyRequest),
    emptyRequest,
    { kind: 'empty' },
  );
  assert.deepEqual(empty, {
    status: 'empty',
    scope,
    request: emptyRequest,
    snapshot: null,
    error: null,
    retry: { scope, previousRequestId: 2 },
  });
});

test('project overview suppresses stale request and stale scope completions', () => {
  const currentRequest = { scope, requestId: 8 };
  const loading = beginProjectOverviewRequest(currentRequest);

  assert.equal(
    projectOverviewRequestIsCurrent({ scope, requestId: 7 }, loading),
    false,
  );
  assert.equal(
    projectOverviewRequestIsCurrent(
      { scope: otherScope, requestId: currentRequest.requestId },
      loading,
    ),
    false,
  );
  assert.equal(projectOverviewRequestIsCurrent(currentRequest, loading), true);

  assert.equal(
    completeProjectOverviewRequest(
      loading,
      { scope, requestId: 7 },
      readyResult(),
    ),
    loading,
  );
  assert.equal(
    completeProjectOverviewRequest(
      loading,
      { scope: otherScope, requestId: 8 },
      readyResult(),
    ),
    loading,
  );
});

test('project overview error state exposes structured retry authority', () => {
  const request = { scope, requestId: 4 };
  const loading = beginProjectOverviewRequest(request);
  const error = {
    code: 'project_overview_load_failed',
    message: 'Unable to load project overview.',
    retryable: true,
  };
  const failed = failProjectOverviewRequest(loading, request, error);

  assert.deepEqual(failed, {
    status: 'error',
    scope,
    request,
    snapshot: null,
    error,
    retry: { scope, previousRequestId: 4 },
  });

  const retryRequest = { scope, requestId: 5 };
  assert.deepEqual(retryProjectOverviewRequest(failed, retryRequest), {
    status: 'loading',
    scope,
    request: retryRequest,
    snapshot: null,
    error: null,
    retry: null,
  });
});

test('project overview suppresses stale failures and fail-closes retry', () => {
  const request = { scope, requestId: 9 };
  const loading = beginProjectOverviewRequest(request);
  const staleError = failProjectOverviewRequest(
    loading,
    { scope, requestId: 8 },
    {
      code: 'stale_error',
      message: 'This result belongs to an older request.',
      retryable: true,
    },
  );
  assert.equal(staleError, loading);

  const terminal = failProjectOverviewRequest(loading, request, {
    code: 'forbidden',
    message: 'Access denied.',
    retryable: false,
  });
  assert.equal(terminal.status, 'error');
  assert.equal(terminal.retry, null);
  assert.equal(
    retryProjectOverviewRequest(terminal, { scope, requestId: 10 }),
    terminal,
  );
  assert.equal(
    retryProjectOverviewRequest(
      failProjectOverviewRequest(loading, request, {
        code: 'retryable',
        message: 'Retry later.',
        retryable: true,
      }),
      { scope: otherScope, requestId: 10 },
    ).status,
    'error',
  );
});
