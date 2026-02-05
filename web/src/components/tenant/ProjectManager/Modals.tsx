/**
 * ProjectManager Modals Components
 *
 * Modal components for creating and editing projects.
 */

import { FC } from 'react';

import { ProjectCreateModal } from '../ProjectCreateModal';
import { ProjectSettingsModal } from '../ProjectSettingsModal';

import { useProjectManagerContext } from './context';

import type { ProjectManagerCreateModalProps, ProjectManagerSettingsModalProps } from './types';

// ============================================================================
// CREATE MODAL
// ============================================================================

export const CreateModal: FC<ProjectManagerCreateModalProps> = ({
  isOpen: propIsOpen,
  onClose,
  onSuccess,
  className: _className = '',
}) => {
  const context = useProjectManagerContext();
  const isControlled = propIsOpen !== undefined;

  // Use controlled value or context state
  const isOpen = isControlled ? propIsOpen : context.isCreateModalOpen;

  // Handle close
  const handleClose = () => {
    if (onClose) {
      onClose();
    } else {
      context.setIsCreateModalOpen(false);
    }
  };

  // Handle success
  const handleSuccess = () => {
    onSuccess?.();
    if (!isControlled) {
      context.setIsCreateModalOpen(false);
    }
  };

  return (
    <ProjectCreateModal
      isOpen={isOpen}
      onClose={handleClose}
      onSuccess={handleSuccess}
    />
  );
};

// ============================================================================
// SETTINGS MODAL
// ============================================================================

export const SettingsModal: FC<ProjectManagerSettingsModalProps> = ({
  project,
  isOpen: propIsOpen,
  onClose,
  onSave,
  onDelete,
  className: _className = '',
}) => {
  const context = useProjectManagerContext();
  const isControlled = propIsOpen !== undefined;

  // Use controlled value or context state
  const isOpen = isControlled ? propIsOpen : context.isSettingsModalOpen;

  // Handle close
  const handleClose = () => {
    if (onClose) {
      onClose();
    } else {
      context.setIsSettingsModalOpen(false);
      context.setSelectedProjectForSettings(null);
    }
  };

  // Handle save
  const handleSave = async (projectId: string, updates: Partial<Project>) => {
    if (onSave) {
      await onSave(projectId, updates);
    } else {
      await context.handleSaveSettings(projectId, updates);
    }
    if (!isControlled) {
      context.setIsSettingsModalOpen(false);
    }
  };

  // Handle delete
  const handleDelete = async (projectId: string) => {
    if (onDelete) {
      await onDelete(projectId);
    } else {
      await context.handleDeleteFromSettings(projectId);
    }
    if (!isControlled) {
      context.setIsSettingsModalOpen(false);
    }
  };

  return (
    <ProjectSettingsModal
      project={project}
      isOpen={isOpen}
      onClose={handleClose}
      onSave={handleSave}
      onDelete={handleDelete}
    />
  );
};

import type { Project } from '@/types/memory';
