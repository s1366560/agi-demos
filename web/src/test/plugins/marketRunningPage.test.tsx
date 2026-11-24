import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

import { MarketDetailView } from '../../../../agi-stack/packages/plugin-marketplace-ui/src/MarketDetailView';
import { marketText } from '../../../../agi-stack/packages/plugin-marketplace-ui/src/pluginMarketText';
import type { MarketDetail } from '../../../../agi-stack/packages/plugin-marketplace-ui/src/pluginMarketTypes';

it('opens the installed route while a newer release is being reviewed', () => {
  const page = { id: 'schedules', title: 'Project schedules', targets: ['web'] as const };
  const detail: MarketDetail = {
    plugin_id: 'automation',
    package_name: '@memstack/automation',
    icon: null,
    display_name: { en: 'Automation' },
    description: {},
    targets: ['web'],
    source: null,
    source_error: null,
    release_error: null,
    latest_version: '2.0.0',
    versions: ['2.0.0', '1.0.0'],
    update_available: true,
    can_manage: true,
    can_execute: true,
    desired_revision: 1,
    previous_version: null,
    current_permissions: [],
    installation: {
      plugin_id: 'automation',
      desired_revision: 1,
      installed_version: '1.0.0',
      running_version: '1.0.0',
      actual_digest: 'old',
      pages: [
        { ...page, routes: ['/project/:projectId/schedules'] },
        { ...page, title: 'Native schedules', targets: ['desktop-renderer'], routes: ['/native'] },
      ],
    },
    release: {
      version: '2.0.0',
      digest: 'new',
      permissions: [],
      commands: [],
      targets: ['web'],
      pages: [{ ...page, title: 'Schedule editor', routes: ['/new-editor'] }],
    },
  };
  const open = vi.fn();
  render(
    <MarketDetailView
      detail={detail}
      text={marketText('en')}
      tenantId="t"
      projectId="p"
      target="web"
      locale="en"
      pluginId="automation"
      onSelect={vi.fn()}
      transport={vi.fn()}
      onOpen={open}
      onVersion={vi.fn()}
      version="2.0.0"
      reload={vi.fn()}
      importLocal={vi.fn()}
    />
  );
  fireEvent.click(screen.getByRole('button', { name: 'Project schedules' }));
  expect(screen.queryByText('Native schedules')).toBeNull();
  expect(open).toHaveBeenCalledWith('/project/p/schedules');
  expect(screen.getByText('Schedule editor')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Schedule editor' })).toBeNull();
});
