import { beforeEach, describe, expect, it, vi } from 'vitest';

import { NewProject } from '../../../pages/tenant/NewProject';
import { fireEvent, render, screen, waitFor } from '../../utils';

const createProject = vi.fn();

vi.mock('../../../stores/project', () => ({
  useProjectStore: () => ({
    createProject,
    isLoading: false,
    error: null,
  }),
}));

vi.mock('../../../stores/tenant', () => ({
  useTenantStore: () => ({
    currentTenant: { id: 'tenant-1' },
  }),
}));

describe('NewProject', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    createProject.mockResolvedValue(undefined);
  });

  it('submits only fields supported by the project create API', async () => {
    const { container } = render(<NewProject />);

    fireEvent.change(screen.getByPlaceholderText('e.g. Finance Knowledge Base'), {
      target: { value: 'Research Memory' },
    });
    fireEvent.change(
      screen.getByPlaceholderText('Briefly describe the purpose of this project...'),
      {
        target: { value: 'Knowledge work for research notes' },
      }
    );

    const form = container.querySelector('form');
    expect(form).not.toBeNull();
    fireEvent.submit(form as HTMLFormElement);

    await waitFor(() => {
      expect(createProject).toHaveBeenCalled();
    });

    const [, payload] = createProject.mock.calls[0] as [string, Record<string, unknown>];
    expect(payload).not.toHaveProperty('status');
    expect(createProject).toHaveBeenCalledWith(
      'tenant-1',
      expect.objectContaining({
        tenant_id: 'tenant-1',
        name: 'Research Memory',
        description: 'Knowledge work for research notes',
      })
    );
  });
});
