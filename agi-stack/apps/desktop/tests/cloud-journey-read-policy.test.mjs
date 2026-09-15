import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const { executeVaultBoundCloudRequest } = require('/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js');
function dependencies(conversationProject = 'project-1') {
  const calls = [];
  return {
    calls,
    loadTrustedSession: async () => ({ version: 1, api_base_url: 'https://cloud.test', runtime_mode: 'cloud', credential_kind: 'cloud_bearer', credential: 'test-only', expires_at: '2099-09-14T00:00:00Z' }),
    fetch: async (url) => {
      const path = new URL(url).pathname; calls.push(path);
      const body = path === '/api/v1/workspace-context'
        ? { context: {tenant_id:'tenant-1',project_id:'project-1',revision:1} }
        : path === '/api/v1/agent/conversations/conversation-1'
          ? {id:'conversation-1',tenant_id:'tenant-1',project_id:conversationProject}
          : {items:[]};
      return new Response(JSON.stringify(body), {headers:{'content-type':'application/json'}});
    },
  };
}
for (const path of ['/api/v1/system/features', '/api/v1/artifacts?project_id=project-1&limit=100', '/api/v1/attachments?conversation_id=conversation-1']) {
  test(`formal journey read is scoped before transport: ${path}`, async () => {
    const deps=dependencies();
    assert.equal((await executeVaultBoundCloudRequest({path,method:'GET'},deps)).status,200);
    if(path.includes('/attachments')) assert.deepEqual(deps.calls,['/api/v1/workspace-context','/api/v1/agent/conversations/conversation-1','/api/v1/attachments']);
  });
}
test('attachment reads reject foreign conversation before reading its attachments', async () => {
  const deps=dependencies('foreign-project');
  await assert.rejects(executeVaultBoundCloudRequest({path:'/api/v1/attachments?conversation_id=conversation-1',method:'GET'},deps), /conversation scope observation failed/);
  assert.equal(deps.calls.includes('/api/v1/attachments'),false);
});
test('catalogs reject foreign projects and exact read rules do not broaden legacy or mutation routes', async () => {
  await assert.rejects(executeVaultBoundCloudRequest({path:'/api/v1/artifacts?project_id=foreign&limit=100',method:'GET'},dependencies()),/project scope mismatch/);
  for (const request of [
    {path:'/api/v1/system/features?tenant_id=tenant-1',method:'GET'},
    {path:'/api/v1/system/features',method:'POST'},
    {path:'/api/v1/artifacts?project_id=project-1&limit=500',method:'GET'},
    {path:'/api/v1/attachments?conversation_id=conversation-1&conversation_id=other',method:'GET'},
    {path:'/api/v1/attachments?conversation_id=conversation-1',method:'POST'},
    {path:'/api/v1/agent/conversations/conversation-1/active-run',method:'GET'},
    {path:'/api/v1/agent/conversations/conversation-1/latest-run',method:'GET'},
    {path:'/api/v1/agent/conversations/conversation-1/participants',method:'GET'},
    {path:'/api/v1/agent/hitl/conversations/conversation-1/pending',method:'GET'},
  ]) await assert.rejects(executeVaultBoundCloudRequest(request,dependencies()), /endpoint is not allowed/,JSON.stringify(request));
});
