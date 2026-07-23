import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  commaSeparatedSearchValues,
  desktopSearchRequestIsComplete,
  nextDesktopSearchLimit,
  searchResponseMayCommit,
  toggleSelectedSearchResult,
} = require('/tmp/agistack-desktop-test-dist/src/features/search/desktopSearchModel.js');

test('desktop search pagination advances in Web-sized increments and stops at 200', () => {
  assert.equal(nextDesktopSearchLimit(50), 100);
  assert.equal(nextDesktopSearchLimit(100), 150);
  assert.equal(nextDesktopSearchLimit(150), 200);
  assert.equal(nextDesktopSearchLimit(200), null);
});

test('desktop search commits only the latest response for the same tenant and project', () => {
  assert.equal(
    searchResponseMayCommit(
      { generation: 3, tenantId: 'tenant-1', projectId: 'project-1' },
      { generation: 3, tenantId: 'tenant-1', projectId: 'project-1' },
    ),
    true,
  );
  assert.equal(
    searchResponseMayCommit(
      { generation: 2, tenantId: 'tenant-1', projectId: 'project-1' },
      { generation: 3, tenantId: 'tenant-1', projectId: 'project-1' },
    ),
    false,
  );
  assert.equal(
    searchResponseMayCommit(
      { generation: 3, tenantId: 'tenant-1', projectId: 'project-1' },
      { generation: 3, tenantId: 'tenant-1', projectId: 'project-2' },
    ),
    false,
  );
});

test('desktop search normalizes structural list inputs and immutable selection changes', () => {
  assert.deepEqual(commaSeparatedSearchValues(' Person, Concept,Person ,, '), [
    'Person',
    'Concept',
  ]);
  assert.deepEqual(toggleSelectedSearchResult([], 'entity-1'), ['entity-1']);
  assert.deepEqual(toggleSelectedSearchResult(['entity-1', 'entity-2'], 'entity-1'), ['entity-2']);
});

test('desktop search mode validation requires the structurally authoritative input', () => {
  assert.equal(
    desktopSearchRequestIsComplete({
      mode: 'semantic',
      query: 'runtime',
      strategy: 'COMBINED_HYBRID_SEARCH_RRF',
      focalNodeUuid: null,
      reranker: null,
      limit: 50,
    }),
    true,
  );
  assert.equal(
    desktopSearchRequestIsComplete({
      mode: 'semantic',
      query: ' ',
      strategy: 'COMBINED_HYBRID_SEARCH_RRF',
      focalNodeUuid: null,
      reranker: null,
      limit: 50,
    }),
    false,
  );
  assert.equal(
    desktopSearchRequestIsComplete({
      mode: 'graphTraversal',
      startEntityUuid: 'entity-1',
      maxDepth: 6,
      relationshipTypes: [],
      limit: 50,
    }),
    false,
  );
  assert.equal(
    desktopSearchRequestIsComplete({
      mode: 'community',
      communityUuid: '',
      includeEpisodes: true,
      limit: 50,
    }),
    false,
  );
});
