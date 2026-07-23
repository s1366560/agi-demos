import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};

const {
  desktopSearchRequestContract,
  normalizeDesktopSearchResponse,
} = require('/tmp/agistack-desktop-test-dist/src/api/searchContract.js');

const scope = {
  tenantId: 'tenant/demo',
  projectId: 'project/search',
};

test('desktop search contracts preserve all five Web modes inside project scope', () => {
  assert.deepEqual(
    desktopSearchRequestContract(
      {
        mode: 'semantic',
        query: 'runtime policy',
        strategy: 'COMBINED_HYBRID_SEARCH_RRF',
        focalNodeUuid: null,
        reranker: 'bge',
        limit: 50,
      },
      scope,
    ),
    {
      path: '/api/v1/search-enhanced/advanced',
      expectedSearchType: 'advanced',
      body: {
        query: 'runtime policy',
        strategy: 'COMBINED_HYBRID_SEARCH_RRF',
        focal_node_uuid: null,
        reranker: 'bge',
        limit: 50,
        tenant_id: 'tenant/demo',
        project_id: 'project/search',
      },
    },
  );

  assert.deepEqual(
    desktopSearchRequestContract(
      {
        mode: 'graphTraversal',
        startEntityUuid: 'entity-1',
        maxDepth: 3,
        relationshipTypes: ['RELATES_TO', 'MENTIONS'],
        limit: 100,
      },
      scope,
    ),
    {
      path: '/api/v1/search-enhanced/graph-traversal',
      expectedSearchType: 'graph_traversal',
      body: {
        start_entity_uuid: 'entity-1',
        max_depth: 3,
        relationship_types: ['RELATES_TO', 'MENTIONS'],
        limit: 100,
        tenant_id: 'tenant/demo',
        project_id: 'project/search',
      },
    },
  );

  assert.deepEqual(
    desktopSearchRequestContract(
      {
        mode: 'temporal',
        query: 'release evidence',
        since: '2026-07-01T00:00:00.000Z',
        until: null,
        limit: 50,
      },
      scope,
    ).body,
    {
      query: 'release evidence',
      since: '2026-07-01T00:00:00.000Z',
      until: null,
      limit: 50,
      tenant_id: 'tenant/demo',
      project_id: 'project/search',
    },
  );

  assert.deepEqual(
    desktopSearchRequestContract(
      {
        mode: 'faceted',
        query: 'agent',
        entityTypes: ['Person', 'Concept'],
        tags: ['runtime', 'verified'],
        since: null,
        limit: 50,
        offset: 0,
      },
      scope,
    ).body,
    {
      query: 'agent',
      entity_types: ['Person', 'Concept'],
      tags: ['runtime', 'verified'],
      since: null,
      limit: 50,
      offset: 0,
      tenant_id: 'tenant/demo',
      project_id: 'project/search',
    },
  );

  assert.deepEqual(
    desktopSearchRequestContract(
      {
        mode: 'community',
        communityUuid: 'community-1',
        includeEpisodes: true,
        limit: 50,
      },
      scope,
    ),
    {
      path: '/api/v1/search-enhanced/community',
      expectedSearchType: 'community',
      body: {
        community_uuid: 'community-1',
        include_episodes: true,
        limit: 50,
        tenant_id: 'tenant/demo',
        project_id: 'project/search',
      },
    },
  );
});

test('desktop search contracts reject invalid structural input before transport', () => {
  assert.throws(
    () =>
      desktopSearchRequestContract(
        {
          mode: 'semantic',
          query: '   ',
          strategy: 'COMBINED_HYBRID_SEARCH_RRF',
          focalNodeUuid: null,
          reranker: null,
          limit: 50,
        },
        scope,
      ),
    /search query/i,
  );
  assert.throws(
    () =>
      desktopSearchRequestContract(
        {
          mode: 'graphTraversal',
          startEntityUuid: 'entity-1',
          maxDepth: 6,
          relationshipTypes: [],
          limit: 50,
        },
        scope,
      ),
    /max depth/i,
  );
  assert.throws(
    () =>
      desktopSearchRequestContract(
        {
          mode: 'community',
          communityUuid: '',
          includeEpisodes: true,
          limit: 50,
        },
        scope,
      ),
    /community uuid/i,
  );
  assert.throws(
    () =>
      desktopSearchRequestContract(
        {
          mode: 'temporal',
          query: 'valid',
          since: null,
          until: null,
          limit: 250,
        },
        scope,
      ),
    /result limit/i,
  );
});

test('desktop search response normalization is strict and preserves display metadata', () => {
  assert.deepEqual(
    normalizeDesktopSearchResponse(
      {
        results: [
          {
            content: 'Policy evidence',
            score: 0.92,
            source: 'Knowledge Graph',
            metadata: {
              uuid: 'entity-1',
              name: 'Runtime policy',
              type: 'Concept',
              created_at: '2026-07-20T10:00:00Z',
              tags: ['runtime'],
            },
          },
        ],
        total: 1,
        search_type: 'advanced',
      },
      'advanced',
    ),
    {
      results: [
        {
          id: 'entity-1',
          title: 'Runtime policy',
          content: 'Policy evidence',
          score: 0.92,
          source: 'Knowledge Graph',
          type: 'Concept',
          createdAt: '2026-07-20T10:00:00Z',
          tags: ['runtime'],
        },
      ],
      total: 1,
      searchType: 'advanced',
      limit: null,
      offset: null,
      facets: null,
    },
  );

  assert.equal(normalizeDesktopSearchResponse({ results: [], total: 0 }, 'advanced'), null);
  assert.equal(
    normalizeDesktopSearchResponse({ results: [], total: 0, search_type: 'temporal' }, 'advanced'),
    null,
  );
  assert.equal(
    normalizeDesktopSearchResponse(
      { results: ['malformed'], total: 1, search_type: 'advanced' },
      'advanced',
    ),
    null,
  );
});
