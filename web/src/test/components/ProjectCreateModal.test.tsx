import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { ProjectCreateModal } from '@/components/tenant/ProjectCreateModal';

import { useProjectStore } from '../../stores/project';
import { useTenantStore } from '../../stores/tenant';

vi.mock('../../stores/project', () => ({
  useProjectStore: vi.fn(),
}));

vi.mock('../../stores/tenant', () => ({
  useTenantStore: vi.fn(),
}));

describe('ProjectCreateModal', () => {
  const mockCreateProject = vi.fn();
  const mockOnClose = vi.fn();
  const mockOnSuccess = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    (useTenantStore as any).mockReturnValue({
      currentTenant: { id: 'tenant-1', name: 'Tenant 1' },
    });
    (useProjectStore as any).mockReturnValue({
      createProject: mockCreateProject,
      isLoading: false,
      error: null,
    });
  });

  it('renders nothing if not open', () => {
    const { container } = render(<ProjectCreateModal isOpen={false} onClose={mockOnClose} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders modal when open', () => {
    render(<ProjectCreateModal isOpen={true} onClose={mockOnClose} />);
    expect(screen.getByText('Create Project', { selector: 'h2' })).toBeInTheDocument();
  });

  it('handles basic form input', () => {
    render(<ProjectCreateModal isOpen={true} onClose={mockOnClose} />);

    const nameInput = screen.getByPlaceholderText('Enter project name');
    const descInput = screen.getByPlaceholderText('Describe the goals and purpose of this project');

    fireEvent.change(nameInput, { target: { value: 'New Project' } });
    fireEvent.change(descInput, { target: { value: 'Description' } });

    expect(nameInput).toHaveValue('New Project');
    expect(descInput).toHaveValue('Description');
  });

  it('handles configuration tabs', () => {
    render(<ProjectCreateModal isOpen={true} onClose={mockOnClose} />);

    // Switch to memory rules
    fireEvent.click(screen.getByText('Memory Rules'));
    expect(screen.getByLabelText('Max Memory Episodes')).toBeInTheDocument();

    // Switch to graph config
    fireEvent.click(screen.getByText('Graph Config'));
    expect(screen.getByLabelText('Max Nodes')).toBeInTheDocument();
  });

  it('submits form', async () => {
    render(<ProjectCreateModal isOpen={true} onClose={mockOnClose} onSuccess={mockOnSuccess} />);

    fireEvent.change(screen.getByPlaceholderText('Enter project name'), {
      target: { value: 'Project 1' },
    });

    const submitButton = screen.getByText('Create Project', { selector: 'button' });
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(mockCreateProject).toHaveBeenCalledWith(
        'tenant-1',
        expect.objectContaining({
          name: 'Project 1',
          status: 'active',
        })
      );
      expect(mockOnSuccess).toHaveBeenCalled();
      expect(mockOnClose).toHaveBeenCalled();
    });
  });
});
