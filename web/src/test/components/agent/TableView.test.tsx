import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

import { TableView } from '@/components/agent/TableView';

describe('TableView', () => {
  const originalCreateObjectURL = URL.createObjectURL;
  const originalRevokeObjectURL = URL.revokeObjectURL;
  const rows = [
    { id: '1', name: 'Alpha', active: true },
    { id: '2', name: 'Beta', active: false },
  ];

  afterEach(() => {
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: originalCreateObjectURL,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: originalRevokeObjectURL,
    });
  });

  it('renders localized controls and formatted boolean values', async () => {
    render(<TableView data={rows} pagination={false} />);

    expect(await screen.findByText('Data Table')).toBeInTheDocument();
    expect(screen.getByText('(2 rows)')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Search table rows' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /export csv/i })).toBeInTheDocument();
    expect(screen.getByText('Yes')).toBeInTheDocument();
    expect(screen.getByText('No')).toBeInTheDocument();
  });

  it('filters rows using displayed cell values', async () => {
    render(<TableView data={rows} pagination={false} />);

    await screen.findByText('Alpha');

    fireEvent.change(screen.getByRole('textbox', { name: 'Search table rows' }), {
      target: { value: 'Beta' },
    });

    expect(screen.queryByText('Alpha')).not.toBeInTheDocument();
    expect(screen.getByText('Beta')).toBeInTheDocument();
    expect(screen.getByText('(1 row)')).toBeInTheDocument();
  });

  it('exports csv with displayed boolean labels', async () => {
    const objectUrl = 'blob:table-view-test';
    const createObjectURLSpy = vi.fn().mockReturnValue(objectUrl);
    const revokeObjectURLSpy = vi.fn();
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: createObjectURLSpy,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: revokeObjectURLSpy,
    });

    render(<TableView data={rows} pagination={false} filename="agents" />);

    await screen.findByText('Alpha');
    fireEvent.click(screen.getByRole('button', { name: /export csv/i }));

    expect(createObjectURLSpy).toHaveBeenCalledTimes(1);
    const blob = createObjectURLSpy.mock.calls[0]?.[0] as Blob;
    await expect(blob.text()).resolves.toContain('Alpha,Yes');
    await expect(blob.text()).resolves.toContain('Beta,No');

    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURLSpy).toHaveBeenCalledWith(objectUrl);
  });
});
