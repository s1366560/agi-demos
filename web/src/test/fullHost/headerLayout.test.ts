import { describe, expect, it } from 'vitest';
import { deriveTopNavigationItems } from '@/config/navigation';
import { hostLinks, layoutHeaderItems, type LinkItem } from '@/fullHost/navigation';

type Context = 'tenant' | 'project';

const scope = (context: Context) => ({ tenantId: 't', ...(context === 'project' ? { projectId: 'p' } : {}) });
const original = (context: Context) => deriveTopNavigationItems(context, scope(context));
const slot = (context: Context, id: string) => {
  const item = original(context).find((candidate) => candidate.id === id);
  if (!item) throw new Error(`No ${context} navigation item ${id}`);
  return item;
};
/** A release opens its page through every route the page declares. */
const page = (context: Context, id: string, paths: string[]): LinkItem => ({
  id: `release/${id}`,
  label: 'From package',
  path: paths[0]!,
  paths,
  plugin: 'memstack-example',
  digest: `sha256:${'a'.repeat(64)}`,
  ...(context === 'project' ? { projectId: 'p' } : {}),
});
const ids = (items: readonly { id: string }[]) => items.map((item) => item.id);

describe('installed workbench header', () => {
  it('keeps original sections and their order while accepting a new package destination', () => {
    const installed = ['users', 'plugins', 'billing'].map((id) =>
      page('tenant', id, [slot('tenant', id).path + '?tenant=t'])
    );
    const extra = { id: 'other/page', label: 'Inventory', path: '/inventory?tenant=t' };

    const header = layoutHeaderItems([extra, ...installed], original('tenant'), 'tenant');

    // Extensions keep their original group, so the package destination joins its section.
    expect(ids(header)).toEqual(['plugins', 'other/page', 'billing', 'users']);
    expect(header[1]).toMatchObject({ ...extra, groupId: 'tenant-extensions-integrations' });
  });

  it('places a page in its original section whatever declared route it opens first', () => {
    const instances = page('tenant', 'instances', [
      '/tenant/t/environments/instances?tenant=t',
      '/tenant/t/instances?tenant=t&businessPackage=memstack-environments',
    ]);

    const header = layoutHeaderItems([instances], original('tenant'), 'tenant');

    expect(header).toEqual([
      {
        ...slot('tenant', 'instances'),
        path: '/tenant/t/instances?tenant=t&businessPackage=memstack-environments',
      },
    ]);
  });

  it('keeps a page below an installed section inside that section', () => {
    const header = layoutHeaderItems(
      [
        page('tenant', 'instances', ['/tenant/t/instances?tenant=t']),
        page('tenant', 'create', ['/tenant/t/instances/create?tenant=t']),
      ],
      original('tenant'),
      'tenant'
    );

    expect(ids(header)).toEqual(['instances']);
  });

  it('keeps every host destination on the path of its original section', () => {
    const translate = (key: string, fallback: string) => fallback;

    for (const link of hostLinks('t', null, translate)) {
      const destination = link.path.split('?')[0];

      expect(
        original('tenant').some((slot) => slot.path.split('?')[0] === destination)
      ).toBe(true);
    }
  });

  it('keeps a section tab out of the header, like organization clusters', () => {
    const translate = (key: string, fallback: string) => fallback;

    const header = layoutHeaderItems(
      [
        ...hostLinks('t', null, translate),
        page('tenant', 'org-clusters', ['/tenant/t/org-settings/clusters?tenant=t']),
      ],
      original('tenant'),
      'tenant'
    );

    expect(ids(header)).toContain('org-settings');
    expect(ids(header)).not.toContain('release/org-clusters');
  });

  it('shows project pages only in a project header', () => {
    const memories = page('project', 'memories', [
      '/tenant/t/project/p/memories?tenant=t&project=p&businessPackage=memstack-knowledge',
    ]);

    const header = layoutHeaderItems(
      [
        { id: 'projects', label: 'Projects', path: '/tenant/t/projects' },
        page('tenant', 'workflow-patterns', ['/tenant/t/patterns?tenant=t']),
        memories,
      ],
      original('project'),
      'project'
    );

    expect(header).toEqual([
      {
        ...slot('project', 'memories'),
        path: '/tenant/t/project/p/memories?tenant=t&project=p&businessPackage=memstack-knowledge',
      },
    ]);
  });

  it('keeps project pages out of the tenant header unless a tenant section opens them', () => {
    const header = layoutHeaderItems(
      [
        page('project', 'chat', [
          '/tenant/t/agent-workspace?tenant=t&project=p',
          '/tenant/t/project/p/memories?tenant=t&project=p',
        ]),
      ],
      original('tenant'),
      'tenant'
    );

    expect(ids(header)).toEqual(['agent-workspace']);
  });
});
