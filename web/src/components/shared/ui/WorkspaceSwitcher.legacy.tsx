import React, { useState, useEffect, useRef } from 'react';

import { useNavigate, useParams } from 'react-router-dom';

import { useProjectStore } from '@/stores/project';
import { useTenantStore } from '@/stores/tenant';

import { Tenant, Project } from '@/types/memory';

interface WorkspaceSwitcherProps {
  mode: 'tenant' | 'project';
}

export const WorkspaceSwitcher: React.FC<WorkspaceSwitcherProps> = ({ mode }) => {
  const navigate = useNavigate();
  const { projectId } = useParams();
  const [isOpen, setIsOpen] = useState(false);
  const [focusedIndex, setFocusedIndex] = useState(-1);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const triggerButtonRef = useRef<HTMLButtonElement>(null);
  const menuItemRefs = useRef<(HTMLButtonElement | null)[]>([]);

  // Stores - use selective selectors to prevent unnecessary re-renders
  const tenants = useTenantStore((state) => state.tenants);
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const setCurrentTenant = useTenantStore((state) => state.setCurrentTenant);
  const listTenants = useTenantStore((state) => state.listTenants);

  const projects = useProjectStore((state) => state.projects);
  const listProjects = useProjectStore((state) => state.listProjects);
  const storeProject = useProjectStore((state) => state.currentProject);

  // Load data if missing
  useEffect(() => {
    if (tenants.length === 0) listTenants();
  }, [tenants.length, listTenants]);

  useEffect(() => {
    if (mode === 'project' && currentTenant && projects.length === 0) {
      listProjects(currentTenant.id);
    }
  }, [mode, currentTenant, projects.length, listProjects]);

  // Reset focused index when dropdown closes
  const wasOpenRef = useRef(false);
  useEffect(() => {
    // Reset when dropdown closes
    if (wasOpenRef.current && !isOpen) {
      // Use setTimeout to defer setState and avoid synchronous setState in effect
      setTimeout(() => {
        setFocusedIndex(-1);
        menuItemRefs.current = [];
      }, 0);
    }
    wasOpenRef.current = isOpen;
  }, [isOpen]);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Get menu items count for keyboard navigation
  const menuItemsCount =
    mode === 'tenant'
      ? tenants.length + 1 // tenants + "Create Tenant" button
      : projects.length + 1; // projects + "Back to Tenant" button

  // Handle keyboard navigation on trigger button
  const handleTriggerKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    switch (e.key) {
      case 'ArrowDown':
      case 'ArrowUp':
      case 'Enter':
      case ' ':
        e.preventDefault();
        setIsOpen(true);
        setFocusedIndex(0);
        // Focus first menu item after dropdown opens
        setTimeout(() => {
          menuItemRefs.current[0]?.focus();
        }, 0);
        break;
      case 'Escape':
        e.preventDefault();
        setIsOpen(false);
        break;
    }
  };

  // Handle keyboard navigation within menu
  const handleMenuKeyDown = (e: React.KeyboardEvent, index: number) => {
    switch (e.key) {
      case 'ArrowDown': {
        e.preventDefault();
        const nextIndex = (index + 1) % menuItemsCount;
        setFocusedIndex(nextIndex);
        menuItemRefs.current[nextIndex]?.focus();
        break;
      }
      case 'ArrowUp': {
        e.preventDefault();
        const prevIndex = (index - 1 + menuItemsCount) % menuItemsCount;
        setFocusedIndex(prevIndex);
        menuItemRefs.current[prevIndex]?.focus();
        break;
      }
      case 'Home': {
        e.preventDefault();
        setFocusedIndex(0);
        menuItemRefs.current[0]?.focus();
        break;
      }
      case 'End': {
        e.preventDefault();
        const lastIndex = menuItemsCount - 1;
        setFocusedIndex(lastIndex);
        menuItemRefs.current[lastIndex]?.focus();
        break;
      }
      case 'Escape': {
        e.preventDefault();
        setIsOpen(false);
        triggerButtonRef.current?.focus();
        break;
      }
      case 'Enter':
      case ' ': {
        // Let the default click handler handle Enter/Space
        // We just prevent default to avoid any unwanted behavior
        if (e.key === ' ') {
          e.preventDefault();
        }
        break;
      }
      case 'Tab': {
        // Allow Tab navigation but close dropdown
        setIsOpen(false);
        break;
      }
    }
  };

  const handleTenantSwitch = (tenant: Tenant) => {
    setCurrentTenant(tenant);
    setIsOpen(false);
    navigate(`/tenant/${tenant.id}`);
  };

  const handleProjectSwitch = (project: Project) => {
    setIsOpen(false);

    // Check current location to decide where to navigate
    const currentPath = window.location.pathname;
    const projectPathPrefix = `/project/${projectId}`;

    if (projectId && currentPath.startsWith(projectPathPrefix)) {
      // If we are already in a project context, preserve the sub-path
      const subPath = currentPath.substring(projectPathPrefix.length);
      navigate(`/project/${project.id}${subPath}`);
    } else {
      // Default to overview
      navigate(`/project/${project.id}`);
    }
  };

  const handleBackToTenant = () => {
    setIsOpen(false);
    if (currentTenant) {
      navigate(`/tenant/${currentTenant.id}`);
    } else {
      navigate('/tenant');
    }
  };

  // Get current project object if in project mode
  const displayProject =
    mode === 'project'
      ? storeProject?.id === projectId
        ? storeProject
        : projects.find((p) => p.id === projectId)
      : null;

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        ref={triggerButtonRef}
        onClick={() => setIsOpen(!isOpen)}
        onKeyDown={handleTriggerKeyDown}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        className="flex items-center gap-2 w-full p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-left focus:outline-none focus:ring-2 focus:ring-primary/50"
      >
        {mode === 'tenant' ? (
          <>
            <div className="bg-primary/10 p-1.5 rounded-md shrink-0 flex items-center justify-center">
              <span className="material-symbols-outlined text-primary text-[20px]">memory</span>
            </div>
            <div className="flex flex-col overflow-hidden">
              <h1 className="text-slate-900 dark:text-white text-sm font-bold leading-none tracking-tight truncate">
                {currentTenant?.name || 'Select Tenant'}
              </h1>
              <p className="text-[10px] text-slate-500 truncate leading-tight opacity-80">
                Tenant Console
              </p>
            </div>
          </>
        ) : (
          <>
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
          </>
        )}
        <span className="material-symbols-outlined text-slate-400 ml-auto text-[18px]">
          unfold_more
        </span>
      </button>

      {/* Dropdown Menu */}
      {isOpen && (
        <div
          role="listbox"
          aria-orientation="vertical"
          aria-labelledby="workspace-switcher-label"
          className="absolute top-full left-0 w-64 mt-2 bg-white dark:bg-[#1e2332] border border-slate-200 dark:border-slate-700 rounded-xl shadow-xl z-50 overflow-hidden animate-in fade-in zoom-in-95 duration-100"
        >
          <div className="p-2">
            {mode === 'tenant' ? (
              <>
                <div
                  id="workspace-switcher-label"
                  className="px-3 py-2 text-xs font-semibold text-slate-400 uppercase tracking-wider"
                >
                  Switch Tenant
                </div>
                {tenants.map((tenant, index) => (
                  <button
                    key={tenant.id}
                    ref={(el) => {
                      menuItemRefs.current[index] = el;
                    }}
                    onClick={() => handleTenantSwitch(tenant)}
                    onKeyDown={(e) => handleMenuKeyDown(e, index)}
                    role="option"
                    aria-selected={currentTenant?.id === tenant.id}
                    tabIndex={focusedIndex === index ? 0 : -1}
                    className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-colors focus:outline-none focus:ring-1 focus:ring-primary/50 ${
                      currentTenant?.id === tenant.id
                        ? 'bg-primary/10 text-primary'
                        : 'text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700'
                    }`}
                  >
                    <div
                      className={`w-2 h-2 rounded-full ${currentTenant?.id === tenant.id ? 'bg-primary' : 'bg-slate-300 dark:bg-slate-600'}`}
                    ></div>
                    <span className="truncate text-sm font-medium">{tenant.name}</span>
                    {currentTenant?.id === tenant.id && (
                      <span className="material-symbols-outlined text-[16px] ml-auto">check</span>
                    )}
                  </button>
                ))}
                <div className="h-px bg-slate-100 dark:bg-slate-700 my-2"></div>
                <button
                  ref={(el) => {
                    menuItemRefs.current[tenants.length] = el;
                  }}
                  onClick={() => navigate('/tenants/new')}
                  onKeyDown={(e) => handleMenuKeyDown(e, tenants.length)}
                  role="option"
                  tabIndex={focusedIndex === tenants.length ? 0 : -1}
                  className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-slate-500 hover:text-slate-900 dark:hover:text-white hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors focus:outline-none focus:ring-1 focus:ring-primary/50"
                >
                  <span className="material-symbols-outlined text-[18px]">add</span>
                  <span className="text-sm font-medium">Create Tenant</span>
                </button>
              </>
            ) : (
              <>
                <div
                  id="workspace-switcher-label"
                  className="px-3 py-2 text-xs font-semibold text-slate-400 uppercase tracking-wider"
                >
                  Switch Project
                </div>
                {projects.map((project, index) => (
                  <button
                    key={project.id}
                    ref={(el) => {
                      menuItemRefs.current[index] = el;
                    }}
                    onClick={() => handleProjectSwitch(project)}
                    onKeyDown={(e) => handleMenuKeyDown(e, index)}
                    role="option"
                    aria-selected={projectId === project.id}
                    tabIndex={focusedIndex === index ? 0 : -1}
                    className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-colors focus:outline-none focus:ring-1 focus:ring-primary/50 ${
                      projectId === project.id
                        ? 'bg-primary/10 text-primary'
                        : 'text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700'
                    }`}
                  >
                    <span className="material-symbols-outlined text-[18px] opacity-70">folder</span>
                    <span className="truncate text-sm font-medium">{project.name}</span>
                    {projectId === project.id && (
                      <span className="material-symbols-outlined text-[16px] ml-auto">check</span>
                    )}
                  </button>
                ))}
                <div className="h-px bg-slate-100 dark:bg-slate-700 my-2"></div>
                <button
                  ref={(el) => {
                    menuItemRefs.current[projects.length] = el;
                  }}
                  onClick={handleBackToTenant}
                  onKeyDown={(e) => handleMenuKeyDown(e, projects.length)}
                  role="option"
                  tabIndex={focusedIndex === projects.length ? 0 : -1}
                  className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-slate-500 hover:text-slate-900 dark:hover:text-white hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors focus:outline-none focus:ring-1 focus:ring-primary/50"
                >
                  <span className="material-symbols-outlined text-[18px]">arrow_back</span>
                  <span className="text-sm font-medium">Back to Tenant</span>
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
