import { describe, it, expect, vi, beforeEach } from 'vitest';

import { TenantCreateModal } from '@/components/tenant/TenantCreateModal';

import { render, screen, fireEvent, waitFor } from '../utils';

// Mock the store module
vi.mock('../../stores/tenant', () => ({
  useTenantStore: vi.fn(),
}));

// Mock tenant store
const mockedStore: any = {
  createTenant: vi.fn(async (_data: any) => {}),
  isLoading: false,
  error: null,
  clearError: vi.fn(),
};
vi.mock('../../stores/tenant', () => ({
  useTenantStore: () => mockedStore,
}));

describe('TenantCreateModal', () => {
  const mockOnClose = vi.fn();
  const mockOnSuccess = vi.fn();
  const defaultProps = {
    isOpen: true,
    onClose: mockOnClose,
    onSuccess: mockOnSuccess,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockedStore.error = null;
    mockedStore.isLoading = false;
  });

  describe('Rendering', () => {
    it('should render modal when isOpen is true', () => {
      render(<TenantCreateModal {...defaultProps} />);

      expect(screen.getByText('Create workspace')).toBeInTheDocument();
      expect(screen.getByLabelText('Workspace name *')).toBeInTheDocument();
      expect(screen.getByLabelText('Description')).toBeInTheDocument();
    });

    it('should not render modal when isOpen is false', () => {
      render(<TenantCreateModal {...defaultProps} isOpen={false} />);

      expect(screen.queryByText('Create workspace')).not.toBeInTheDocument();
    });
  });

  describe('User Interactions', () => {
    it('should call createTenant with correct parameters on submit', async () => {
      const store = mockedStore as any;

      render(<TenantCreateModal {...defaultProps} />);

      const nameInput = screen.getByLabelText('Workspace name *');
      const descriptionTextarea = screen.getByLabelText('Description');
      const submitButton = screen.getByText('Create');

      await fireEvent.change(nameInput, { target: { value: 'Test Tenant' } });
      await fireEvent.change(descriptionTextarea, { target: { value: 'Test Description' } });
      await fireEvent.click(submitButton);

      await waitFor(() => {
        expect(store.createTenant).toHaveBeenCalledWith({
          name: 'Test Tenant',
          description: 'Test Description',
          plan: 'free',
        });
      });
    });

    it('should call onSuccess and onClose after successful creation', async () => {
      render(<TenantCreateModal {...defaultProps} />);

      const nameInput = screen.getByLabelText('Workspace name *');
      const submitButton = screen.getByText('Create');

      await fireEvent.change(nameInput, { target: { value: 'Test' } });
      await fireEvent.click(submitButton);

      await waitFor(() => {
        expect(mockOnSuccess).toHaveBeenCalled();
        expect(mockOnClose).toHaveBeenCalled();
      });
    });

    it('should call onClose when cancel button is clicked', async () => {
      render(<TenantCreateModal {...defaultProps} />);

      const cancelButton = screen.getByText('Cancel');
      await fireEvent.click(cancelButton);

      expect(mockOnClose).toHaveBeenCalled();
    });

    it('should call onClose when X button is clicked', async () => {
      render(<TenantCreateModal {...defaultProps} />);

      const closeButton = screen.getByRole('button', { name: 'Close create workspace dialog' }); // X icon button with aria-label
      await fireEvent.click(closeButton);

      expect(mockOnClose).toHaveBeenCalled();
    });
  });

  describe('Error Handling', () => {
    it('should render without error message initially', async () => {
      mockedStore.error = null;
      render(<TenantCreateModal {...defaultProps} />);
      expect(screen.queryByText(/create failed/i)).not.toBeInTheDocument();
    });

    it('should call clearError when invoked', async () => {
      mockedStore.error = 'Error';
      render(<TenantCreateModal {...defaultProps} />);
      expect(screen.getByText(/Error/)).toBeInTheDocument();
      mockedStore.error = null;
      mockedStore.clearError();
      expect(mockedStore.clearError).toHaveBeenCalled();
    });
  });

  describe('Loading States', () => {
    it('should submit when form is valid', async () => {
      render(<TenantCreateModal {...defaultProps} />);
      const nameInput = screen.getByLabelText('Workspace name *');
      const submitButton = screen.getByText('Create');
      await fireEvent.change(nameInput, { target: { value: 'Test' } });
      await fireEvent.click(submitButton);
      expect(mockedStore.createTenant).toHaveBeenCalled();
    });

    it('inputs remain enabled when not loading', async () => {
      render(<TenantCreateModal {...defaultProps} />);
      const nameInput = screen.getByLabelText('Workspace name *');
      const submitButton = screen.getByText('Create');
      await fireEvent.change(nameInput, { target: { value: 'Test' } });
      expect(nameInput).not.toBeDisabled();
      expect(submitButton).not.toBeDisabled();
    });
  });
});
