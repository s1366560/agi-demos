import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { McpServerDrawer } from '@/components/mcp/McpServerDrawer';

const flushConsoleWarnings = () => new Promise((resolve) => setTimeout(resolve, 20));

describe('McpServerDrawer', () => {
  it('does not initialize the Ant Design form while hidden', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    render(<McpServerDrawer open={false} server={null} onClose={vi.fn()} onSuccess={vi.fn()} />);
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
    const { rerender } = render(
      <McpServerDrawer open={false} server={null} onClose={vi.fn()} onSuccess={vi.fn()} />
    );

    rerender(<McpServerDrawer open server={null} onClose={vi.fn()} onSuccess={vi.fn()} />);

    expect(await screen.findByRole('button', { name: 'Create' })).toBeInTheDocument();
  });
});
