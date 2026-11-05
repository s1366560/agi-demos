import assert from 'node:assert/strict';
import { once } from 'node:events';
import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const compiled = '/tmp/agistack-desktop-test-dist/apps/desktop';
const { executeVaultBoundCloudRequest } = require(
  `${compiled}/electron/main/cloudRequestPolicy.js`,
);
const { decodeConversationSessionProjection } = require(
  `${compiled}/src/features/session/sessionProjectionModel.js`,
);
const fixture = JSON.parse(
  readFileSync(
    new URL('../../server/tests/fixtures/rust-cloud-chat-session.json', import.meta.url),
    'utf8',
  ),
);
const scope = {
  conversationId: 'cloud-chat',
  tenantId: 'tenant',
  projectId: 'project',
  workspaceId: null,
};

for (const condition of ['allowed', 'missing-detail', 'wrong-tenant']) {
  test(`Rust cloud session observes authoritative conversation before projection: ${condition}`, async () => {
    const paths = [];
    const server = createServer((request, response) => {
      const url = new URL(request.url, 'http://localhost');
      paths.push(url.pathname);
      response.setHeader('Content-Type', 'application/json');
      if (url.pathname === '/api/v1/workspace-context') {
        response.end(
          JSON.stringify({
            context: { tenant_id: 'tenant', project_id: 'project', workspace_id: null },
          }),
        );
      } else if (url.pathname === '/api/v1/agent/conversations/cloud-chat') {
        if (condition === 'missing-detail')
          response.writeHead(404).end(JSON.stringify({ detail: 'Not found' }));
        else
          response.end(
            JSON.stringify({
              ...fixture.conversation,
              tenant_id: condition === 'wrong-tenant' ? 'other' : 'tenant',
            }),
          );
      } else if (url.pathname === '/api/v1/agent/trace/runs/cloud-chat') response.end('[]');
      else if (url.pathname.endsWith('/session')) response.end(JSON.stringify(fixture));
      else response.writeHead(500).end(JSON.stringify({ detail: 'unexpected request' }));
    });
    server.listen(0, '127.0.0.1');
    await once(server, 'listening');
    try {
      const dependencies = {
        loadTrustedSession: async () => ({
          version: 1,
          api_base_url: `http://127.0.0.1:${server.address().port}`,
          runtime_mode: 'cloud',
          credential_kind: 'cloud_bearer',
          credential: 'owned-fixture-only',
          expires_at: null,
        }),
        fetch: globalThis.fetch,
      };
      const operation = executeVaultBoundCloudRequest(
        {
          path: '/api/v1/agent/trace/runs/cloud-chat',
          method: 'GET',
        },
        dependencies,
      );
      if (condition !== 'allowed') {
        await assert.rejects(operation, /cloud request conversation scope observation failed/);
        assert.equal(
          paths.some((path) => path.endsWith('/session')),
          false,
        );
      } else {
        const trace = await operation;
        assert.equal(trace.status, 200);
        const result = await executeVaultBoundCloudRequest(
          {
            path: '/api/v1/agent/conversations/cloud-chat/session?tenant_id=tenant&project_id=project',
            method: 'GET',
          },
          dependencies,
        );
        assert.equal(result.status, 200);
        const decoded = decodeConversationSessionProjection(result.body, scope);
        assert.ok(decoded);
        assert.equal(decoded.currentRun.plan_version_id, null);
        assert.equal(decoded.currentRun.id, 'chat-run');
        assert.equal(decoded.currentRun.permission_profile, 'read_only');
        assert.deepEqual(paths, [
          '/api/v1/workspace-context',
          '/api/v1/agent/conversations/cloud-chat',
          '/api/v1/agent/trace/runs/cloud-chat',
          '/api/v1/workspace-context',
          '/api/v1/agent/conversations/cloud-chat/session',
        ]);
      }
    } finally {
      await new Promise((resolve) => server.close(resolve));
    }
  });
}

test('strict Rust chat projection still requires plan envelope and exact run scope', () => {
  const missing = structuredClone(fixture);
  delete missing.current_plan;
  assert.equal(decodeConversationSessionProjection(missing, scope), null);
  const foreign = structuredClone(fixture);
  foreign.execution.current_run.project_id = 'other';
  assert.equal(decodeConversationSessionProjection(foreign, scope), null);
});
