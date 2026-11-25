import { describe, expect, it } from 'vitest';

import { installationDestination } from '../../../../agi-stack/packages/plugin-marketplace-ui/src/installationReturn';

const scope = { tenantId: 't1', projectId: 'p1' };
const active = {
  plugin_id: 'atlas',
  desired_revision: 2,
  running_version: '2',
  installed_version: '2',
  actual_digest: 'sha256:example',
  pages: [
    {
      id: 'entry',
      title: 'Atlas',
      routes: ['/project/:projectId/atlas/:entry'],
      targets: ['web' as const],
    },
  ],
};
describe('returning after installing the owner of a bookmark', () => {
  it('restores the path, query and anchor verbatim', () => {
    const link = '/project/p1/atlas/42?view=table&tenant=t1#row';
    expect(installationDestination(link, scope, active, 'web')).toBe(link);
  });
  it.each([
    '/project/p2/atlas/42',
    '/project/p1/atlas/42?tenant=t2',
    '/project/p1/atlas/42?businessPackage=other',
    '/project/p1/other/42',
    '//elsewhere/atlas/42',
  ])('retains the market for an unrelated destination %s', (link) => {
    expect(installationDestination(link, scope, active, 'web')).toBeNull();
  });
  it('requires an active Web entry', () => {
    expect(
      installationDestination('/project/p1/atlas/42', scope, { ...active, actual_digest: null }, 'web')
    ).toBeNull();
  });
});
