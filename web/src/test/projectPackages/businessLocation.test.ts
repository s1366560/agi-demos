import { describe, expect, it } from 'vitest';
import { businessLocation, businessRouteScope } from '../../projectPackages/businessLocation';

const project = { id: 'p', tenant_id: 't' };
describe('business page links', () => {
  it('restores signed pages from their own URL, including unknown plugins', () => {
    const link = businessLocation('/boards', 't', 'p', 'board-package');
    expect(businessRouteScope(link.pathname, new URLSearchParams(link.search))).toEqual({
      tenant: 't',
      project: 'p',
      plugin: 'board-package',
    });
    expect(businessRouteScope('/tenant/t/project/p/workspaces', new URLSearchParams())).toEqual({
      tenant: 't',
      project: 'p',
      plugin: null,
    });
  });
  it('keeps administration, ambiguous scopes and other tenants outside business routing', () => {
    for (const [path, search] of [
      ['/tenant/t/plugins', 'tenant=t&project=p&businessPackage=plugin'],
      ['/tenant/t/project/p/boards', 'project=other'],
      ['/boards', 'businessPackage=plugin&tenant=t&project=p&project=x'],
      ['/tenant/other/agent-workspace', ''],
      ['/login', 'tenant=t&project=p&businessPackage=plugin'],
    ] as const)
      expect(businessRouteScope(path, new URLSearchParams(search), project)).toBeNull();
  });
});
