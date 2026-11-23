import { describe, expect, it } from 'vitest';

import { matchingPageProjects } from '../../projectPackages/routeScope';

const first = { tenant_id: 't', project_id: 'one' };
const second = { tenant_id: 't', project_id: 'two' };
const find = (path: string, query = '') =>
  matchingPageProjects([first, second], path, new URLSearchParams(query));

describe('project selection for package deep links', () => {
  it('keeps ambiguous package URLs available for explicit project selection', () => {
    expect(find('/qa/labels')).toEqual([first, second]);
    expect(find('/qa/labels', 'tenant=t')).toEqual([first, second]);
    expect(find('/qa/labels', 'tenant=missing')).toEqual([]);
  });
  it('uses the project embedded after the tenant', () => {
    expect(find('/tenant/t/project/two/workspaces')).toEqual([second]);
    expect(find('/workspaces', 'tenant=t&project=two')).toEqual([second]);
  });
  it('refuses missing, malformed and conflicting project contexts', () => {
    expect(find('/tenant/t/project/two/workspaces', 'project=one')).toEqual([]);
    expect(find('/project/missing/notes')).toEqual([]);
    expect(find('/qa', 'project=one&project=two')).toEqual([]);
    expect(find('/project/%/notes')).toEqual([]);
  });
});
