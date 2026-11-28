import { describe, expect, it } from 'vitest';
import { businessLocation, businessRouteScope, tenantPageScope } from '../../projectPackages/businessLocation';

const project = { id: 'p', tenant_id: 't' };
describe('business page links', () => {
  it('lets the tenant redirect resolve an unscoped workspace creation bookmark', () => {
    const query = new URLSearchParams();
    expect(tenantPageScope('/tenant/workspaces/new', query)).toBeNull();
    expect(businessRouteScope('/tenant/workspaces/new', query, project)).toBeNull();
  });
  it('resolves the installed clusters tab only within its tenant', () => {
    const path = '/tenant/t/org-settings/clusters';
    expect(tenantPageScope(path, new URLSearchParams())).toBe('t');
    expect(tenantPageScope(path, new URLSearchParams('tenant=other'))).toBeNull();
    expect(tenantPageScope(path + '/edit', new URLSearchParams())).toBeNull();
    expect(tenantPageScope('/tenant/t/org-settings/info', new URLSearchParams())).toBeNull();
    expect(businessRouteScope(path, new URLSearchParams(), project)).toBeNull();
  });
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
  it('restores the bookmarked project even before the project picker loads', () => {
    const path = '/tenant/t/agent-workspace/conversation';
    expect(businessRouteScope(path, new URLSearchParams('projectId=bookmarked'), project))
      .toEqual({ tenant: 't', project: 'bookmarked', plugin: null });
    for (const q of ['project=p&projectId=x', 'projectId=p&projectId=x'])
      expect(businessRouteScope(path, new URLSearchParams(q), project)).toBeNull();
    expect(businessRouteScope('/tenant/t/project/p/boards', new URLSearchParams('projectId=x'))).toBeNull();
  });
  it('opens a package detail with its original query and anchor', () => {
    const link = businessLocation('/boards/7?view=table&tenant=other#details', 't', 'p', 'board-package');
    expect(link.pathname).toBe('/boards/7');
    expect(link.hash).toBe('#details');
    const query = new URLSearchParams(link.search);
    expect(query.get('view')).toBe('table');
    expect(query.getAll('tenant')).toEqual(['t']);
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
