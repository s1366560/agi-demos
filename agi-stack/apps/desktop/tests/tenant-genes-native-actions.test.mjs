import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';

const require = createRequire(import.meta.url);
const { createTenantGenesClient } = require(
  '/tmp/agistack-desktop-test-dist/src/features/tenant-admin/tenantGenesClient.js',
);

const config = Object.freeze({
  apiBaseUrl: 'https://cloud.memstack.test',
  deviceAuthorizationBaseUrl: 'https://cloud.memstack.test',
  apiKey: 'trusted-session',
  localApiToken: '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  mode: 'cloud',
  workspaceRoot: '/workspace',
});
const scope = Object.freeze({ authority: 'cloud', tenantId: 'tenant-1' });
const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

test('gene subresource actions keep tenant authority in a valid query string', async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    const parsed = new URL(String(url));
    const method = init.method ?? 'GET';
    assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer trusted-session');
    if (parsed.pathname === '/api/v1/workspace-context') {
      return json({
        context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 41 },
        membership_role: 'owner',
      });
    }
    calls.push(`${method} ${parsed.pathname}${parsed.search}`);
    if (method === 'DELETE') return new Response(null, { status: 204 });
    if (parsed.pathname.endsWith('/reviews') && method === 'GET') {
      return json({ items: [reviewPayload()], total: 1, page: 1, page_size: 50 });
    }
    if (parsed.pathname.endsWith('/reviews')) return json(reviewPayload());
    if (parsed.pathname.endsWith('/ratings')) return json({ id: 'rating-1' });
    if (parsed.pathname.includes('/instances/')) return json({ id: 'install-1' });
    return json(genePayload());
  };

  const client = createTenantGenesClient(config);
  await client.createGene(scope, { name: 'Review', slug: 'review' });
  await client.updateGene(scope, 'gene-1', { name: 'Review two' });
  await client.deleteGene(scope, 'gene-1');
  await client.publishGene(scope, 'gene-1');
  await client.unpublishGene(scope, 'gene-1');
  await client.installGene(scope, 'instance-1', 'gene-1');
  await client.rateGene(scope, 'gene-1', 5, 'Useful');
  await client.listReviews(scope, 'gene-1');
  await client.createReview(scope, 'gene-1', 5, 'Useful');
  await client.deleteReview(scope, 'gene-1', 'review-1');

  assert.deepEqual(calls, [
    'POST /api/v1/genes/?tenant_id=tenant-1',
    'PUT /api/v1/genes/gene-1?tenant_id=tenant-1',
    'DELETE /api/v1/genes/gene-1?tenant_id=tenant-1',
    'POST /api/v1/genes/gene-1/publish?tenant_id=tenant-1',
    'POST /api/v1/genes/gene-1/unpublish?tenant_id=tenant-1',
    'POST /api/v1/genes/instances/instance-1/install?tenant_id=tenant-1',
    'POST /api/v1/genes/gene-1/ratings?tenant_id=tenant-1',
    'GET /api/v1/genes/gene-1/reviews?tenant_id=tenant-1&page=1&page_size=50',
    'POST /api/v1/genes/gene-1/reviews?tenant_id=tenant-1',
    'DELETE /api/v1/genes/gene-1/reviews/review-1?tenant_id=tenant-1',
  ]);
});

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function genePayload() {
  return {
    id: 'gene-1',
    name: 'Review',
    slug: 'review',
    tenant_id: 'tenant-1',
    description: 'Review code',
    category: 'development',
    version: '1.0.0',
    visibility: 'tenant',
    install_count: 1,
    avg_rating: 5,
    is_published: true,
    created_at: '2026-08-05T00:00:00Z',
    updated_at: null,
  };
}

function reviewPayload() {
  return {
    id: 'review-1',
    gene_id: 'gene-1',
    user_id: 'user-1',
    rating: 5,
    content: 'Useful',
    created_at: '2026-08-05T00:00:00Z',
  };
}
