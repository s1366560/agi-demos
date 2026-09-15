// Smoke test: spawn sidecar, create session, list tenants/projects.
import { SidecarHarness } from './lib/harness.mjs';

const harness = new SidecarHarness({
  logPath: new URL('./logs/smoke.log', import.meta.url).pathname,
});
try {
  await harness.start();
  await harness.createSession();
  const me = await harness.http('/api/v1/auth/me');
  console.log('auth/me:', JSON.stringify(me).slice(0, 300));
  const tenants = await harness.http('/api/v1/tenants');
  console.log('tenants:', JSON.stringify(tenants).slice(0, 500));
  const projects = await harness.http('/api/v1/projects');
  console.log('projects:', JSON.stringify(projects).slice(0, 800));
  const wsCtx = await harness.http('/api/v1/workspace-context');
  console.log('workspace-context:', JSON.stringify(wsCtx).slice(0, 300));
  const providerTypes = await harness.http('/api/v1/llm-providers/types');
  console.log('provider types:', JSON.stringify(providerTypes).slice(0, 600));
} finally {
  await harness.stop();
}
