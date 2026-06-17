import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { McpServerDrawer } from '@/components/mcp/McpServerDrawer';

const flushConsoleWarnings = () => new Promise((resolve) => setTimeout(resolve, 20));

const renderInTenantRoute = (ui: React.ReactElement) =>
  render(
    <MemoryRouter initialEntries={['/tenant/tenant-1/mcp-servers']}>
      <Routes>
        <Route path="/tenant/:tenantId/mcp-servers" element={ui} />
      </Routes>
    </MemoryRouter>
  );

describe('McpServerDrawer', () => {
  it('does not initialize the Ant Design form while hidden', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    renderInTenantRoute(
      <McpServerDrawer open={false} server={null} onClose={vi.fn()} onSuccess={vi.fn()} />
    );
    await flushConsoleWarnings();

    const disconnectedFormWarning = consoleErrorSpy.mock.calls.find((call) =>
      call.some(
        (message) =>
          String(message).includes('useForm') && String(message).includes('not connected')
      )
    );
    expect(disconnectedFormWarning).toBeUndefined();

    consoleErrorSpy.mockRestore();
  });

  it('mounts the form when opened after being hidden', async () => {
    const { rerender } = renderInTenantRoute(
      <McpServerDrawer open={false} server={null} onClose={vi.fn()} onSuccess={vi.fn()} />
    );

    rerender(
      <MemoryRouter initialEntries={['/tenant/tenant-1/mcp-servers']}>
        <Routes>
          <Route
            path="/tenant/:tenantId/mcp-servers"
            element={<McpServerDrawer open server={null} onClose={vi.fn()} onSuccess={vi.fn()} />}
          />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByRole('button', { name: 'Create' })).toBeInTheDocument();
  });
});
