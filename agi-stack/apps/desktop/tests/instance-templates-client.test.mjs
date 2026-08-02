import assert from 'node:assert/strict';
import { test } from 'node:test';

const {
  createInstanceTemplatesClient,
  InstanceTemplatesUnavailableError,
} = await import(
  '/tmp/agistack-desktop-test-dist/src/features/instance-templates/instanceTemplatesClient.js'
);

function runtimeConfig(mode, overrides = {}) {
  return {
    mode,
    apiBaseUrl: 'https://api.example.test',
    deviceAuthorizationBaseUrl: 'https://api.example.test',
    apiKey: 'cloud-token',
    localApiToken: 'local-token',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    workspaceRoot: '/workspace',
    ...overrides,
  };
}

function response(payload, status = 200) {
  return new Response(payload === null ? null : JSON.stringify(payload), {
    status,
    headers: payload === null ? {} : { 'content-type': 'application/json' },
  });
}

function template(overrides = {}) {
  return {
    id: 'template-1',
    name: 'Starter',
    slug: 'starter',
    tenant_id: 'tenant-1',
    description: 'A safe starter template',
    icon: null,
    image_version: 'v1',
    default_config: { cpu: 2 },
    is_published: false,
    is_featured: false,
    install_count: 3,
    created_by: 'user-1',
    created_at: '2026-08-02T08:00:00Z',
    updated_at: null,
    secret: 'must-not-cross-renderer',
    ...overrides,
  };
}

test('Cloud Instance Templates uses the production list, detail, items, and lifecycle contracts', async () => {
  const calls = [];
  const client = createInstanceTemplatesClient(runtimeConfig('cloud'), {
    fetch: async (input, init) => {
      const url = String(input);
      calls.push({ url, init });
      if (url.endsWith('/instance-templates/template-1/items')) {
        return response([
          {
            id: 'item-1',
            template_id: 'template-1',
            item_type: 'gene',
            item_slug: 'gene.safe',
            display_order: 1,
            created_at: '2026-08-02T08:01:00Z',
          },
        ]);
      }
      if (url.endsWith('/instance-templates/template-1/clone')) {
        return response(template({ id: 'template-2', name: 'Starter Copy' }), 201);
      }
      if (url.endsWith('/instance-templates/template-1/publish')) {
        return response(template({ is_published: true }));
      }
      if (url.endsWith('/instance-templates/template-1')) {
        if (init?.method === 'DELETE') return response(null, 204);
        return response(template());
      }
      if (
        url.endsWith('/instance-templates/') ||
        url.includes('/instance-templates/?')
      ) {
        if (init?.method === 'POST') return response(template(), 201);
        return response({
          templates: [template()],
          total: 1,
          page: 2,
          page_size: 10,
        });
      }
      throw new Error(`unexpected request ${url}`);
    },
  });
  const scope = { authority: 'cloud', tenantId: 'tenant-1' };

  const page = await client.list(scope, {
    page: 2,
    pageSize: 10,
    isPublished: false,
  });
  assert.equal(page.templates[0].name, 'Starter');
  assert.equal(JSON.stringify(page).includes('must-not-cross-renderer'), false);
  assert.match(
    calls[0].url,
    /instance-templates\/\?page=2&page_size=10&is_published=false$/u,
  );
  assert.equal(calls[0].init.headers.get('Authorization'), 'Bearer cloud-token');

  const detail = await client.get(scope, 'template-1');
  const items = await client.listItems(scope, 'template-1');
  const created = await client.create(scope, {
    name: 'Starter',
    slug: 'starter',
    description: null,
    defaultConfig: { cpu: 2 },
  });
  const published = await client.publish(scope, 'template-1');
  const cloned = await client.clone(scope, 'template-1', 'Starter Copy');
  await client.delete(scope, 'template-1');
  assert.equal(detail.defaultConfig.cpu, 2);
  assert.equal(items[0].itemSlug, 'gene.safe');
  assert.equal(created.id, 'template-1');
  assert.equal(published.isPublished, true);
  assert.equal(cloned.id, 'template-2');
  assert.equal(calls.at(-1).init.method, 'DELETE');
});

test('Instance Templates fails closed on scope drift and never calls Local network', async () => {
  let fetchCalls = 0;
  const local = createInstanceTemplatesClient(runtimeConfig('local'), {
    fetch: async () => {
      fetchCalls += 1;
      return response({});
    },
  });
  await assert.rejects(
    () => local.list({ authority: 'local', tenantId: 'tenant-1' }),
    (error) =>
      error instanceof InstanceTemplatesUnavailableError &&
      error.reasonCode === 'local_instance_template_authority_unavailable',
  );
  await assert.rejects(
    () => local.get({ authority: 'local', tenantId: 'tenant-other' }, 'template-1'),
    (error) =>
      error instanceof InstanceTemplatesUnavailableError &&
      error.reasonCode === 'instance_templates_runtime_scope_mismatch',
  );
  assert.equal(fetchCalls, 0);
});
