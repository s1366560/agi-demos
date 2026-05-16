/**
 * Tests for ProjectSettingsModal component
 */

import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import '@testing-library/jest-dom';
import { ProjectSettingsModal } from '@/components/tenant/ProjectSettingsModal';

// Mock projectService
vi.mock('../../services/projectService', () => ({
  projectService: {
    updateProject: vi.fn(),
    deleteProject: vi.fn(),
  },
}));

describe('ProjectSettingsModal', () => {
  const mockOnClose = vi.fn();
  const mockOnSave = vi.fn();
  const mockOnDelete = vi.fn();

  const defaultProps = {
    project: {
      id: 'project-1',
      name: 'Test Project',
      description: 'Test Description',
      is_public: false,
      tenant_id: 'tenant-1',
      owner_id: 'user-1',
      created_at: new Date().toISOString(),
    },
    isOpen: true,
    onClose: mockOnClose,
    onSave: mockOnSave,
    onDelete: mockOnDelete,
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  function createDeferred<T = void>() {
    let resolve!: (value: T | PromiseLike<T>) => void;
    let reject!: (reason?: unknown) => void;
    const promise = new Promise<T>((promiseResolve, promiseReject) => {
      resolve = promiseResolve;
      reject = promiseReject;
    });
    return { promise, resolve, reject };
  }

  describe('Rendering', () => {
    it('should render modal when isOpen is true', () => {
      render(<ProjectSettingsModal {...defaultProps} />);

      expect(screen.getByText('Project Settings')).toBeInTheDocument();
      expect(screen.getByDisplayValue('Test Project')).toBeInTheDocument();
      expect(screen.getByDisplayValue('Test Description')).toBeInTheDocument();
    });

    it('should not render modal when isOpen is false', () => {
      render(<ProjectSettingsModal {...defaultProps} isOpen={false} />);

      expect(screen.queryByText('Project Settings')).not.toBeInTheDocument();
    });
  });

  describe('Form Interactions', () => {
    it('should update project name input', async () => {
      render(<ProjectSettingsModal {...defaultProps} />);

      const nameInput = screen.getByPlaceholderText('Enter project name');
      await fireEvent.change(nameInput, { target: { value: 'New Project Name' } });

      expect(nameInput).toHaveValue('New Project Name');
    });

    it('should update description textarea', async () => {
      render(<ProjectSettingsModal {...defaultProps} />);

      const descriptionTextarea = screen.getByPlaceholderText('Add project description...');
      await fireEvent.change(descriptionTextarea, { target: { value: 'New Description' } });

      expect(descriptionTextarea).toHaveValue('New Description');
    });

    it('should toggle public checkbox', async () => {
      render(<ProjectSettingsModal {...defaultProps} />);

      const publicCheckbox = screen.getByLabelText('Public Project');
      await fireEvent.click(publicCheckbox);

      expect(publicCheckbox).toBeChecked();
    });
  });

  describe('Save Functionality', () => {
    it('should call onSave when save button is clicked', async () => {
      const saveDeferred = createDeferred();
      mockOnSave.mockReturnValueOnce(saveDeferred.promise);
      render(<ProjectSettingsModal {...defaultProps} />);

      const saveButton = screen.getByText('Save Changes');
      await fireEvent.click(saveButton);

      await waitFor(() => {
        expect(saveButton).toBeDisabled();
      });
      await waitFor(() => {
        expect(mockOnSave).toHaveBeenCalled();
      });
      await act(async () => {
        saveDeferred.resolve();
      });
      await waitFor(() => {
        expect(mockOnClose).toHaveBeenCalled();
      });
      await waitFor(() => {
        expect(saveButton).not.toBeDisabled();
      });
    });

    it('should call onClose when cancel button is clicked', async () => {
      render(<ProjectSettingsModal {...defaultProps} />);

      const cancelButton = screen.getByText('Cancel');
      await fireEvent.click(cancelButton);

      expect(mockOnClose).toHaveBeenCalled();
    });
  });

  describe('Delete Functionality', () => {
    it('should show confirmation dialog when delete button is clicked', async () => {
      render(<ProjectSettingsModal {...defaultProps} />);

      const deleteButton = screen.getByText('Delete Project');
      await fireEvent.click(deleteButton);

      expect(screen.getByText('Confirm Delete')).toBeInTheDocument();
    });

    it('should call onDelete when confirmed', async () => {
      const deleteDeferred = createDeferred();
      mockOnDelete.mockReturnValueOnce(deleteDeferred.promise);
      render(<ProjectSettingsModal {...defaultProps} />);

      const deleteButton = screen.getByText('Delete Project');
      await fireEvent.click(deleteButton);

      const confirmButton = screen.getByText('Confirm Delete');
      await fireEvent.click(confirmButton);
      await waitFor(() => {
        expect(confirmButton).toBeDisabled();
      });
      await waitFor(() => {
        expect(mockOnDelete).toHaveBeenCalled();
      });
      await act(async () => {
        deleteDeferred.resolve();
      });
      await waitFor(() => {
        expect(screen.queryByText('Confirm Delete')).not.toBeInTheDocument();
      });
    });

    it('should not call deleteProject when cancelled', async () => {
      const { projectService } = await import('../../services/projectService');
      global.confirm = vi.fn(() => false);

      render(<ProjectSettingsModal {...defaultProps} />);

      const deleteButton = screen.getByText('Delete Project');
      await fireEvent.click(deleteButton);

      expect(projectService.deleteProject).not.toHaveBeenCalled();
    });
  });

  describe('Error Handling', () => {
    it('should display error when update fails', async () => {
      const saveDeferred = createDeferred();
      const failingOnSave = vi.fn().mockReturnValueOnce(saveDeferred.promise);
      const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);

      render(<ProjectSettingsModal {...defaultProps} onSave={failingOnSave} />);

      const saveButton = screen.getByText('Save Changes');
      await fireEvent.click(saveButton);

      await waitFor(() => {
        expect(saveButton).toBeDisabled();
      });
      await waitFor(() => {
        expect(failingOnSave).toHaveBeenCalled();
      });
      await act(async () => {
        saveDeferred.reject(new Error('Update failed'));
      });
      await waitFor(() => {
        expect(saveButton).not.toBeDisabled();
      });
      expect(consoleError).toHaveBeenCalledWith('Failed to update project:', expect.any(Error));
      consoleError.mockRestore();
    });

    it('should display error when delete fails', async () => {
      const deleteDeferred = createDeferred();
      const failingOnDelete = vi.fn().mockReturnValueOnce(deleteDeferred.promise);
      const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);

      render(<ProjectSettingsModal {...defaultProps} onDelete={failingOnDelete} />);

      const deleteButton = screen.getByText('Delete Project');
      await fireEvent.click(deleteButton);

      const confirmButton = screen.getByText('Confirm Delete');
      expect(confirmButton).toBeInTheDocument();
      await fireEvent.click(confirmButton);
      await waitFor(() => {
        expect(confirmButton).toBeDisabled();
      });
      await waitFor(() => {
        expect(failingOnDelete).toHaveBeenCalled();
      });
      await act(async () => {
        deleteDeferred.reject(new Error('Delete failed'));
      });
      await waitFor(() => {
        expect(screen.queryByText('Confirm Delete')).not.toBeInTheDocument();
      });
      expect(consoleError).toHaveBeenCalledWith('Failed to delete project:', expect.any(Error));
      consoleError.mockRestore();
    });
  });

  describe('Form Validation', () => {
    it('should show error when project name is empty', async () => {
      render(<ProjectSettingsModal {...defaultProps} />);

      const nameInput = screen.getByPlaceholderText('Enter project name');
      await fireEvent.change(nameInput, { target: { value: '' } });

      const saveButton = screen.getByText('Save Changes');
      await fireEvent.click(saveButton);

      // Should not call updateProject with empty name
      const { projectService } = await import('../../services/projectService');
      expect(projectService.updateProject).not.toHaveBeenCalled();
    });
  });
});
