import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

import { MarketDetailView } from '../../../../agi-stack/packages/plugin-marketplace-ui/src/MarketDetailView';
import { marketText } from '../../../../agi-stack/packages/plugin-marketplace-ui/src/pluginMarketText';
import type { MarketDetail } from '../../../../agi-stack/packages/plugin-marketplace-ui/src/pluginMarketTypes';

function renderUpdate(transport = vi.fn()) {
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
  const reload = vi.fn();
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
      transport={transport}
      onOpen={open}
      onVersion={vi.fn()}
      version="2.0.0"
      reload={reload}
      importLocal={vi.fn()}
    />
  );
  return { open, reload };
}

it('opens the installed route while a newer release is being reviewed', () => {
  const { open } = renderUpdate();
  fireEvent.click(screen.getByRole('button', { name: 'Project schedules' }));
  expect(screen.queryByText('Native schedules')).toBeNull();
  expect(open).toHaveBeenCalledWith('/project/p/schedules');
  expect(screen.getByText('Schedule editor')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Schedule editor' })).toBeNull();
});

it.each([
  { digest: 'new', revision: 2, recovered: true },
  { digest: 'other', revision: 2, recovered: false },
  { digest: 'new', revision: 1, recovered: false },
])(
  'reconciles a lost apply response with digest $digest and revision $revision',
  async ({ digest, revision, recovered }) => {
    HTMLDialogElement.prototype.showModal ??= function () {
      this.open = true;
    };
    HTMLDialogElement.prototype.close ??= function () {
      this.open = false;
    };
    const transport = vi
      .fn()
      .mockRejectedValueOnce(new Error('connection timed out'))
      .mockResolvedValueOnce({
        plugin_id: 'automation',
        running_version: '2.0.0',
        installed_version: '2.0.0',
        actual_digest: digest,
        desired_revision: revision,
      });
    const { reload } = renderUpdate(transport);
    fireEvent.click(screen.getByRole('button', { name: 'Update to 2.0.0' }));
    fireEvent.click(screen.getByRole('button', { name: 'Approve update' }));
    if (recovered) {
      await waitFor(() => expect(reload).toHaveBeenCalledOnce());
    } else {
      expect(await screen.findByRole('alert')).toHaveTextContent('connection timed out');
      expect(reload).not.toHaveBeenCalled();
    }
    expect(transport.mock.calls.map(([url, options]) => [url, options.method ?? 'GET'])).toEqual([
      ['/api/v1/platform-plugins/v2/optional-business/npm/apply', 'POST'],
      ['/api/v1/platform-plugins/v2/optional-business/automation?tenant_id=t&project_id=p', 'GET'],
    ]);
  }
);
