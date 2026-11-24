import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

import { packageRoute } from '../../../../agi-stack/apps/desktop/src/packageHost/packageRoute';

vi.mock('../../../../agi-stack/apps/desktop/src/packageHost/InstalledRoutePage', () => ({
  InstalledRoutePage: ({ tenantId, projectId, segment }: {
    tenantId: string;
    projectId: string;
    segment: string;
  }) => <output>{[tenantId, projectId, segment].join('/')}</output>,
}));

it('restores a scoped blackboard bookmark from the installation and preserves local routing', async () => {
  let local = false;
  const loadLocal = vi.fn(async () => ({
    routeId: 'board', capability: 'board', localPolicy: 'native_equivalent' as const,
    disposition: 'implemented' as const, availability: 'available' as const,
    reasonCode: null, Surface: () => null,
  }));
  const load = packageRoute('board', 'blackboard', 'project', {
    isLocal: () => local,
    load: loadLocal,
  });
  const module = await load();
  render(<module.Surface module={module} context={{ tenantId: 't', projectId: 'p', workspaceId: 'w/1' }} />);
  expect(screen.getByRole('status')).toHaveTextContent('t/p/blackboard?workspaceId=w%2F1');
  expect(loadLocal).not.toHaveBeenCalled();
  local = true;
  await load();
  expect(loadLocal).toHaveBeenCalledOnce();
});
