import { describe, expect, it } from 'vitest';

import { deriveAgentChatTenantId } from '@/components/agent/agentChatScope';

describe('deriveAgentChatTenantId', () => {
  it('prefers the route tenant over a stale project tenant', () => {
    expect(
      deriveAgentChatTenantId({
        routeTenantId: 'route-tenant',
        projectTenantId: 'stale-project-tenant',
      })
    ).toBe('route-tenant');
  });

  it('falls back to the project tenant when the route tenant is unavailable', () => {
    expect(
      deriveAgentChatTenantId({
        routeTenantId: null,
        projectTenantId: 'project-tenant',
      })
    ).toBe('project-tenant');
  });

  it('returns an empty tenant id when no scoped context is available', () => {
    expect(
      deriveAgentChatTenantId({
        routeTenantId: undefined,
        projectTenantId: null,
      })
    ).toBe('');
  });
});
