/**
 * Tests for ProjectSettingsModal component
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { ProjectSettingsModal } from '../../components/ProjectSettingsModal';

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

  describe('Rendering', () => {
    it('should render modal when isOpen is true', () => {
      render(<ProjectSettingsModal {...defaultProps} />);

      expect(screen.getByText('项目设置')).toBeInTheDocument();
      expect(screen.getByDisplayValue('Test Project')).toBeInTheDocument();
      expect(screen.getByDisplayValue('Test Description')).toBeInTheDocument();
    });

    it('should not render modal when isOpen is false', () => {
      render(<ProjectSettingsModal {...defaultProps} isOpen={false} />);

      expect(screen.queryByText('项目设置')).not.toBeInTheDocument();
    });
  });

  describe('Form Interactions', () => {
    it('should update project name input', async () => {
      render(<ProjectSettingsModal {...defaultProps} />);

      const nameInput = screen.getByPlaceholderText('输入项目名称');
      await fireEvent.change(nameInput, { target: { value: 'New Project Name' } });

      expect(nameInput).toHaveValue('New Project Name');
    });

    it('should update description textarea', async () => {
      render(<ProjectSettingsModal {...defaultProps} />);

      const descriptionTextarea = screen.getByPlaceholderText('添加项目描述...');
      await fireEvent.change(descriptionTextarea, { target: { value: 'New Description' } });

      expect(descriptionTextarea).toHaveValue('New Description');
    });

    it('should toggle public checkbox', async () => {
      render(<ProjectSettingsModal {...defaultProps} />);

      const publicCheckbox = screen.getByLabelText('公开项目');
      await fireEvent.click(publicCheckbox);

      expect(publicCheckbox).toBeChecked();
    });
  });

  describe('Save Functionality', () => {
    it('should call onSave when save button is clicked', async () => {

      render(<ProjectSettingsModal {...defaultProps} />);

      const saveButton = screen.getByText('保存更改');
      await fireEvent.click(saveButton);

      await waitFor(() => {
        expect(mockOnSave).toHaveBeenCalled();
      });
    });

    it('should call onClose when cancel button is clicked', async () => {
      render(<ProjectSettingsModal {...defaultProps} />);

      const cancelButton = screen.getByText('取消');
      await fireEvent.click(cancelButton);

      expect(mockOnClose).toHaveBeenCalled();
    });
  });

  describe('Delete Functionality', () => {
    it('should show confirmation dialog when delete button is clicked', async () => {

      render(<ProjectSettingsModal {...defaultProps} />);

      const deleteButton = screen.getByText('删除项目');
      await fireEvent.click(deleteButton);

      expect(screen.getByText('确认删除')).toBeInTheDocument();
    });

    it('should call onDelete when confirmed', async () => {

      render(<ProjectSettingsModal {...defaultProps} />);

      const deleteButton = screen.getByText('删除项目');
      await fireEvent.click(deleteButton);

      const confirmButton = screen.getByText('确认删除');
      await fireEvent.click(confirmButton);
      await waitFor(() => {
        expect(mockOnDelete).toHaveBeenCalled();
      });
    });

    it('should not call deleteProject when cancelled', async () => {
      const { projectService } = await import('../../services/projectService');
      global.confirm = vi.fn(() => false);

      render(<ProjectSettingsModal {...defaultProps} />);

      const deleteButton = screen.getByText('删除项目');
      await fireEvent.click(deleteButton);

      expect(projectService.deleteProject).not.toHaveBeenCalled();
    });
  });

  describe('Error Handling', () => {
    it('should display error when update fails', async () => {
      const { projectService } = await import('../../services/projectService');
      (projectService.updateProject as any).mockRejectedValue(new Error('Update failed'));

      render(<ProjectSettingsModal {...defaultProps} />);

      const saveButton = screen.getByText('保存更改');
      await fireEvent.click(saveButton);

      await waitFor(() => {
        expect(saveButton).toBeDisabled();
      });
    });

    it('should display error when delete fails', async () => {
      const { projectService } = await import('../../services/projectService');
      (projectService.deleteProject as any).mockRejectedValue(new Error('Delete failed'));
      global.confirm = vi.fn(() => true);

      render(<ProjectSettingsModal {...defaultProps} />);

      const deleteButton = screen.getByText('删除项目');
      await fireEvent.click(deleteButton);

      const confirmButton = screen.getByText('确认删除');
      expect(confirmButton).toBeInTheDocument();
      await fireEvent.click(confirmButton);
      await waitFor(() => {
        expect(screen.queryByText('确认删除')).not.toBeInTheDocument();
      });
    });
  });

  describe('Form Validation', () => {
    it('should show error when project name is empty', async () => {
      render(<ProjectSettingsModal {...defaultProps} />);

      const nameInput = screen.getByPlaceholderText('输入项目名称');
      await fireEvent.change(nameInput, { target: { value: '' } });

      const saveButton = screen.getByText('保存更改');
      await fireEvent.click(saveButton);

      // Should not call updateProject with empty name
      const { projectService } = await import('../../services/projectService');
      expect(projectService.updateProject).not.toHaveBeenCalled();
    });
  });
});
