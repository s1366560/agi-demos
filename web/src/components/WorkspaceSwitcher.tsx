import React, { useState, useEffect, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useTenantStore } from '../stores/tenant'
import { useProjectStore } from '../stores/project'
import { Tenant, Project } from '../types/memory'

interface WorkspaceSwitcherProps {
    mode: 'tenant' | 'project'
}

export const WorkspaceSwitcher: React.FC<WorkspaceSwitcherProps> = ({ mode }) => {
    const navigate = useNavigate()
    const { projectId } = useParams()
    const [isOpen, setIsOpen] = useState(false)
    const dropdownRef = useRef<HTMLDivElement>(null)

    // Stores
    const { tenants, currentTenant, setCurrentTenant, listTenants } = useTenantStore()
    const { projects, listProjects, currentProject: storeProject } = useProjectStore()

    // Load data if missing
    useEffect(() => {
        if (tenants.length === 0) listTenants()
    }, [tenants.length, listTenants])

    useEffect(() => {
        if (mode === 'project' && currentTenant && projects.length === 0) {
            listProjects(currentTenant.id)
        }
    }, [mode, currentTenant, projects.length, listProjects])

    // Close dropdown when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
                setIsOpen(false)
            }
        }
        document.addEventListener('mousedown', handleClickOutside)
        return () => document.removeEventListener('mousedown', handleClickOutside)
    }, [])

    const handleTenantSwitch = (tenant: Tenant) => {
        setCurrentTenant(tenant)
        setIsOpen(false)
        navigate(`/tenant/${tenant.id}`)
    }

    const handleProjectSwitch = (project: Project) => {
        setIsOpen(false)

        // Check current location to decide where to navigate
        const currentPath = window.location.pathname
        const projectPathPrefix = `/project/${projectId}`

        if (projectId && currentPath.startsWith(projectPathPrefix)) {
            // If we are already in a project context, preserve the sub-path
            const subPath = currentPath.substring(projectPathPrefix.length)
            navigate(`/project/${project.id}${subPath}`)
        } else {
            // Default to overview
            navigate(`/project/${project.id}`)
        }
    }

    const handleBackToTenant = () => {
        setIsOpen(false)
        if (currentTenant) {
            navigate(`/tenant/${currentTenant.id}`)
        } else {
            navigate('/tenant')
        }
    }

    // Get current project object if in project mode
    const displayProject = mode === 'project'
        ? (storeProject?.id === projectId ? storeProject : projects.find(p => p.id === projectId))
        : null

    return (
        <div className="relative" ref={dropdownRef}>
            <button
                onClick={() => setIsOpen(!isOpen)}
                className="flex items-center gap-2 w-full p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-left"
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
                            <p className="text-[10px] text-slate-500 truncate leading-tight opacity-80">Tenant Console</p>
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
                <div className="absolute top-full left-0 w-64 mt-2 bg-white dark:bg-[#1e2332] border border-slate-200 dark:border-slate-700 rounded-xl shadow-xl z-50 overflow-hidden animate-in fade-in zoom-in-95 duration-100">
                    <div className="p-2">
                        {mode === 'tenant' ? (
                            <>
                                <div className="px-3 py-2 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                                    Switch Tenant
                                </div>
                                {tenants.map(tenant => (
                                    <button
                                        key={tenant.id}
                                        onClick={() => handleTenantSwitch(tenant)}
                                        className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${currentTenant?.id === tenant.id
                                            ? 'bg-primary/10 text-primary'
                                            : 'text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700'
                                            }`}
                                    >
                                        <div className={`w-2 h-2 rounded-full ${currentTenant?.id === tenant.id ? 'bg-primary' : 'bg-slate-300 dark:bg-slate-600'}`}></div>
                                        <span className="truncate text-sm font-medium">{tenant.name}</span>
                                        {currentTenant?.id === tenant.id && (
                                            <span className="material-symbols-outlined text-[16px] ml-auto">check</span>
                                        )}
                                    </button>
                                ))}
                                <div className="h-px bg-slate-100 dark:bg-slate-700 my-2"></div>
                                <button
                                    onClick={() => navigate('/tenants/new')}
                                    className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-slate-500 hover:text-slate-900 dark:hover:text-white hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
                                >
                                    <span className="material-symbols-outlined text-[18px]">add</span>
                                    <span className="text-sm font-medium">Create Tenant</span>
                                </button>
                            </>
                        ) : (
                            <>
                                <div className="px-3 py-2 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                                    Switch Project
                                </div>
                                {projects.map(project => (
                                    <button
                                        key={project.id}
                                        onClick={() => handleProjectSwitch(project)}
                                        className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${projectId === project.id
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
                                    onClick={handleBackToTenant}
                                    className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-slate-500 hover:text-slate-900 dark:hover:text-white hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
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
    )
}
