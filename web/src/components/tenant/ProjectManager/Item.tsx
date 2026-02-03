/**
 * ProjectManager.Item Component
 *
 * Individual project item component.
 */

import React, { FC } from 'react';
import { Folder, Settings, Trash2 } from 'lucide-react';
import { useProjectManagerContext } from './context';
import type { ProjectManagerItemProps } from './types';

export const Item: FC<ProjectManagerItemProps> = ({
  project,
  isSelected: propIsSelected,
  onClick,
  onSettingsClick,
  onDeleteClick,
  variant = 'card',
  className = '',
}) => {
  const context = useProjectManagerContext();

  // Determine if this project is selected
  const isSelected =
    propIsSelected !== undefined
      ? propIsSelected
      : context.currentProject?.id === project.id;

  // Handle item click
  const handleClick = () => {
    if (onClick) {
      onClick(project);
    } else {
      context.handleProjectSelect(project);
    }
  };

  // Handle settings button click
  const handleSettingsClick = (e: React.MouseEvent) => {
    if (onSettingsClick) {
      onSettingsClick(project, e);
    } else {
      context.handleOpenSettings(project, e);
    }
  };

  // Handle delete button click
  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (onDeleteClick) {
      onDeleteClick(project, e);
    } else {
      context.handleDeleteProject(project.id);
    }
  };

  // Base classes
  const baseClasses =
    'p-4 rounded-lg border cursor-pointer transition-all';

  // Selected state classes
  const selectedClasses = isSelected
    ? 'border-blue-500 dark:border-blue-400 bg-blue-50 dark:bg-blue-900/20'
    : 'border-gray-200 dark:border-slate-700 hover:border-gray-300 dark:hover:border-slate-600 hover:bg-gray-50 dark:hover:bg-slate-800';

  return (
    <div
      data-testid="project-item"
      data-project-id={project.id}
      data-selected={isSelected}
      className={`${baseClasses} ${selectedClasses} ${className}`}
      onClick={handleClick}
    >
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center space-x-2">
          <div className="w-8 h-8 bg-gradient-to-br from-green-500 to-blue-600 rounded-lg flex items-center justify-center">
            <Folder className="h-4 w-4 text-white" />
          </div>
          <div>
            <h4 className="text-sm font-medium text-gray-900 dark:text-white">
              {project.name}
            </h4>
          </div>
        </div>
        <div className="flex items-center space-x-1">
          <button
            data-testid="settings-btn"
            onClick={handleSettingsClick}
            className="p-1 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 rounded-md transition-colors"
            title="项目设置"
          >
            <Settings className="h-4 w-4" />
          </button>
          <button
            data-testid="delete-btn"
            onClick={handleDeleteClick}
            className="p-1 text-gray-400 dark:text-slate-500 hover:text-red-600 dark:hover:text-red-400 rounded-md transition-colors"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {project.description && (
        <p className="text-sm text-gray-600 dark:text-slate-400 mb-3 line-clamp-2">
          {project.description}
        </p>
      )}

      <div className="flex items-center justify-between text-xs text-gray-500 dark:text-slate-500">
        <span>创建于 {new Date(project.created_at).toLocaleDateString()}</span>
      </div>
    </div>
  );
};
