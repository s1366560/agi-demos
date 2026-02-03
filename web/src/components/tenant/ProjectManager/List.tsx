/**
 * ProjectManager.List Component
 *
 * Container component for rendering a list of projects.
 */

import React, { FC } from 'react';
import { useProjectManagerContext } from './context';
import type { ProjectManagerListProps } from './types';
import type { Project } from '@/types/memory';

export const List: FC<ProjectManagerListProps> = ({
  children,
  onProjectClick,
  layout = 'grid',
  gridCols = 'md:grid-cols-2 lg:grid-cols-3',
  className = '',
}) => {
  const context = useProjectManagerContext();

  // Filter projects based on search and filter
  const filteredProjects = context.projects.filter((project) => {
    const matchesSearch =
      project.name.toLowerCase().includes(context.searchTerm.toLowerCase()) ||
      project.description?.toLowerCase().includes(context.searchTerm.toLowerCase());
    const matchesFilter = context.filterStatus === 'all';
    return matchesSearch && matchesFilter;
  });

  // Get grid or list layout class
  const layoutClass = layout === 'grid' ? `grid ${gridCols}` : 'flex flex-col space-y-2';

  // Handle project click
  const handleProjectClick = (project: Project) => {
    if (onProjectClick) {
      onProjectClick(project);
    } else {
      context.handleProjectSelect(project);
    }
  };

  return (
    <div className={`gap-4 ${layoutClass} ${className}`} data-testid="project-manager-list">
      {typeof children === 'function'
        ? filteredProjects.map((project, index) => children(project, index))
        : children}
    </div>
  );
};
