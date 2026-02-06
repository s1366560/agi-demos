/**
 * ProjectWorkspaceSwitcher - Convenience component for project switching
 *
 * Pre-configured WorkspaceSwitcher for project mode.
 */

import { useEffect } from 'react';

import { useNavigate, useParams } from 'react-router-dom';

import { useProjectStore } from '@/stores/project';
import { useTenantStore } from '@/stores/tenant';

import { WorkspaceSwitcherRoot, WorkspaceSwitcherTrigger, WorkspaceSwitcherMenu } from './compound';
import { ProjectList } from './ProjectList';

import type { Project } from '@/types/memory';

import type { ProjectWorkspaceSwitcherProps } from './types';

export const ProjectWorkspaceSwitcher: React.FC<ProjectWorkspaceSwitcherProps> = ({
  currentProjectId: propProjectId,
  onProjectSelect,
  onBackToTenant,
  backToTenantLabel = 'Back to Tenant',
  triggerClassName = '',
  menuClassName = '',
}) => {
  const navigate = useNavigate();
  const { projectId: routeProjectId } = useParams();
  const currentProjectId = propProjectId ?? routeProjectId ?? null;

  // Store hooks - use selective selectors to prevent unnecessary re-renders
  const projects = useProjectStore((state) => state.projects);
  const currentProject = useProjectStore((state) => state.currentProject);
  const listProjects = useProjectStore((state) => state.listProjects);
  const currentTenant = useTenantStore((state) => state.currentTenant);

  // Load data if missing
  useEffect(() => {
    if (currentTenant && projects.length === 0) {
      listProjects(currentTenant.id);
    }
  }, [currentTenant, projects.length, listProjects]);

  // Get current project object
  const displayProject =
    currentProject?.id === currentProjectId
      ? currentProject
      : projects.find((p) => p.id === currentProjectId);

  const handleProjectSelect = (project: Project) => {
    onProjectSelect?.(project);

    // Check current location to decide where to navigate
    const currentPath = window.location.pathname;
    const projectPathPrefix = `/project/${currentProjectId}`;

    if (currentProjectId && currentPath.startsWith(projectPathPrefix)) {
      // If we are already in a project context, preserve the sub-path
      const subPath = currentPath.substring(projectPathPrefix.length);
      navigate(`/project/${project.id}${subPath}`);
    } else {
      // Default to overview
      navigate(`/project/${project.id}`);
    }
  };

  const handleBackToTenantClick = () => {
    onBackToTenant?.();
    if (currentTenant) {
      navigate(`/tenant/${currentTenant.id}`);
    } else {
      navigate('/tenant');
    }
  };

  return (
    <WorkspaceSwitcherRoot mode="project">
      <WorkspaceSwitcherTrigger className={triggerClassName}>
        <div className="bg-primary/10 rounded-md p-1.5 flex items-center justify-center text-primary shrink-0">
          <span className="material-symbols-outlined text-[20px]">dataset</span>
        </div>
        <div className="flex flex-col overflow-hidden">
          <h1 className="text-sm font-bold text-slate-900 dark:text-white leading-none truncate">
            {displayProject?.name || 'Select Project'}
          </h1>
          <p className="text-[10px] text-slate-500 dark:text-slate-400 font-medium truncate leading-tight opacity-80 mt-0.5">
            {currentTenant?.name}
          </p>
        </div>
        <span className="material-symbols-outlined text-slate-400 ml-auto text-[18px]">
          unfold_more
        </span>
      </WorkspaceSwitcherTrigger>

      <WorkspaceSwitcherMenu label="Switch Project" className={menuClassName}>
        <ProjectList
          projects={projects}
          currentProjectId={currentProjectId}
          onProjectSelect={handleProjectSelect}
          onBackToTenant={handleBackToTenantClick}
          backToTenantLabel={backToTenantLabel}
        />
      </WorkspaceSwitcherMenu>
    </WorkspaceSwitcherRoot>
  );
};
