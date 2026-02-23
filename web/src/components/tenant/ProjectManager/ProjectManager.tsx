/**
 * ProjectManager Root Component
 *
 * Main component that provides context for all sub-components.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';


import { useProjectStore } from '@/stores/project';
import { useTenantStore } from '@/stores/tenant';

import { projectService } from '@/services/projectService';

import { ProjectManagerContext } from './context';
import { Item } from './Item';
import { List } from './List';
import { CreateModal, SettingsModal } from './Modals';
import { Search } from './Search';
import { Loading, Empty, Error } from './States';

import type { Project } from '@/types/memory';

import type { ProjectManagerProps } from './types';

export const Root: React.FC<ProjectManagerProps> = ({
  children,
  variant = 'controlled',
  onProjectSelect,
  className = '',
}) => {
  const { currentTenant } = useTenantStore();
  const {
    projects,
    currentProject,
    listProjects,
    deleteProject,
    setCurrentProject,
    isLoading,
    error,
    clearError,
  } = useProjectStore();

  // Local state for search and filter
  const [searchTerm, setSearchTerm] = useState('');
  const [filterStatus, setFilterStatus] = useState('all');

  // Modal state
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isSettingsModalOpen, setIsSettingsModalOpen] = useState(false);
  const [selectedProjectForSettings, setSelectedProjectForSettings] = useState<Project | null>(
    null
  );

  // Load projects when tenant changes
  useEffect(() => {
    if (currentTenant) {
      listProjects(currentTenant.id);
    }
  }, [currentTenant, listProjects]);

  // Handle project selection
  const handleProjectSelect = useCallback(
    (project: Project) => {
      setCurrentProject(project);
      onProjectSelect?.(project);
    },
    [setCurrentProject, onProjectSelect]
  );

  // Handle project deletion
  const handleDeleteProject = useCallback(
    async (projectId: string) => {
      if (!currentTenant) return;

      if (window.confirm('确定要删除这个项目吗？此操作不可恢复。')) {
        try {
          await deleteProject(currentTenant.id, projectId);
        } catch {
          // Error handled in store
        }
      }
    },
    [currentTenant, deleteProject]
  );

  // Handle opening settings modal
  const handleOpenSettings = useCallback((project: Project, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedProjectForSettings(project);
    setIsSettingsModalOpen(true);
  }, []);

  // Handle saving settings
  const handleSaveSettings = useCallback(
    async (projectId: string, updates: Partial<Project>) => {
      try {
        await projectService.updateProject(projectId, {
          name: updates.name || '',
          description: updates.description,
          is_public: updates.is_public || false,
        });
        // Refresh project list
        if (currentTenant) {
          await listProjects(currentTenant.id);
        }
        setIsSettingsModalOpen(false);
      } catch (err) {
        console.error('Failed to update project:', err);
        throw err;
      }
    },
    [currentTenant, listProjects]
  );

  // Handle delete from settings modal
  const handleDeleteFromSettings = useCallback(
    async (projectId: string) => {
      if (!currentTenant) return;
      try {
        await deleteProject(currentTenant.id, projectId);
        setIsSettingsModalOpen(false);
      } catch (err) {
        console.error('Failed to delete project:', err);
        throw err;
      }
    },
    [currentTenant, deleteProject]
  );

  // Filter projects based on search and filter status
  const filteredProjects = useMemo(() => {
    return projects.filter((project) => {
      const matchesSearch =
        project.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        project.description?.toLowerCase().includes(searchTerm.toLowerCase());
      const matchesFilter = filterStatus === 'all';
      return matchesSearch && matchesFilter;
    });
  }, [projects, searchTerm, filterStatus]);

  // Context value
  const contextValue = useMemo(
    () => ({
      projects,
      currentProject,
      isLoading,
      error,
      currentTenant,
      searchTerm,
      setSearchTerm,
      filterStatus,
      setFilterStatus,
      clearError,
      isCreateModalOpen,
      setIsCreateModalOpen,
      isSettingsModalOpen,
      setIsSettingsModalOpen,
      selectedProjectForSettings,
      setSelectedProjectForSettings,
      handleProjectSelect,
      handleDeleteProject,
      handleOpenSettings,
      handleSaveSettings,
      handleDeleteFromSettings,
      onProjectSelect,
    }),
    [
      projects,
      currentProject,
      isLoading,
      error,
      currentTenant,
      searchTerm,
      filterStatus,
      clearError,
      isCreateModalOpen,
      isSettingsModalOpen,
      selectedProjectForSettings,
      handleProjectSelect,
      handleDeleteProject,
      handleOpenSettings,
      handleSaveSettings,
      handleDeleteFromSettings,
      onProjectSelect,
    ]
  );

  // Render content based on variant
  const renderContent = () => {
    // Controlled variant - render children as-is
    if (variant === 'controlled') {
      return <>{children}</>;
    }

    // Full variant - auto-render all sub-components
    if (variant === 'full') {
      // No tenant state
      if (!currentTenant) {
        return <Empty variant="no-tenant" />;
      }

      // Loading state
      if (isLoading) {
        return <Loading />;
      }

      // Error state
      if (error) {
        return <Error error={error} onDismiss={clearError} />;
      }

      // Empty state
      if (filteredProjects.length === 0) {
        return (
          <Empty
            variant={searchTerm ? 'no-results' : 'no-projects'}
            showCreateButton={!searchTerm}
            onCreateClick={() => setIsCreateModalOpen(true)}
          />
        );
      }

      // Render all components
      return (
        <>
          <Search />
          <List>{(project) => <Item key={project.id} project={project} />}</List>
          <CreateModal />
          {selectedProjectForSettings && <SettingsModal project={selectedProjectForSettings} />}
        </>
      );
    }

    return null;
  };

  return (
    <ProjectManagerContext.Provider value={contextValue}>
      <div className={className}>{renderContent()}</div>
    </ProjectManagerContext.Provider>
  );
};
