import React, { useEffect, useState, memo } from 'react';

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { useProjectStore } from '../../stores/project';
import { useTenantStore } from '../../stores/tenant';

import type { TFunction } from 'i18next';
import { formatDateOnly } from '@/utils/date';

// Hoist formatStorage outside component to avoid recreation on every render (rendering-hoist-jsx)
const formatStorage = (bytes: number): string => {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
};

// Hoist formatTime outside component to avoid recreation on every render (rendering-hoist-jsx)
// Note: Using TFunction type directly since useTranslation returns a tuple
const createFormatTime = (t: TFunction) => {
  return (dateString?: string | null): string => {
    if (!dateString) return t('common.time.never');
    const date = new Date(dateString);
    const now = new Date();
    const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000);

    if (diffInSeconds < 60) return t('common.time.justNow');
    if (diffInSeconds < 3600)
      return `${Math.floor(diffInSeconds / 60)}${t('common.time.minutes')} ${t('common.time.ago', { time: '' })}`;
    if (diffInSeconds < 86400)
      return `${Math.floor(diffInSeconds / 3600)}${t('common.time.hours')} ${t('common.time.ago', { time: '' })}`;
    if (diffInSeconds < 604800)
      return `${Math.floor(diffInSeconds / 86400)}${t('common.time.days')} ${t('common.time.ago', { time: '' })}`;
    return formatDateOnly(date);
  };
};

interface ProjectListProps {
  // Props can be added later if needed
}

// Use memo to prevent unnecessary re-renders (rerender-memo)
const ProjectListInner: React.FC<ProjectListProps> = () => {
  const { t } = useTranslation();
  const { currentTenant } = useTenantStore();
  const { listProjects, deleteProject, projects, isLoading } = useProjectStore();
  const [search, setSearch] = useState('');
  const [activeMenu, setActiveMenu] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');

  useEffect(() => {
    if (currentTenant) {
      listProjects(currentTenant.id, { search });
    }
  }, [currentTenant, search, listProjects]);

  // Create formatTime function using translation hook
  const formatTime = createFormatTime(t);

  const handleDelete = async (projectId: string) => {
    if (!currentTenant) return;
    if (window.confirm(t('tenant.projects.deleteConfirm'))) {
      try {
        await deleteProject(currentTenant.id, projectId);
        setActiveMenu(null);
      } catch (error) {
        console.error('Failed to delete project:', error);
      }
    }
  };

  if (!currentTenant) {
    return <div className="p-8 text-center text-slate-500">{t('tenant.overview.loading')}</div>;
  }

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-8">
      {/* Header Area */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">
            {t('tenant.projects.title')}
          </h1>
          <p className="text-sm text-slate-500">{t('tenant.projects.subtitle')}</p>
        </div>
        <Link to={`/tenant/${currentTenant.id}/projects/new`}>
          <button className="bg-primary hover:bg-primary-dark text-white px-5 py-2.5 rounded-lg text-sm font-medium shadow-lg shadow-primary/20 flex items-center gap-2 transition-all active:scale-95">
            <span className="material-symbols-outlined text-lg">add</span>
            {t('tenant.projects.create')}
          </button>
        </Link>
      </div>

      {/* Toolbar: Search & Filters */}
      <div className="flex flex-col md:flex-row gap-4 justify-between items-center bg-white dark:bg-surface-dark p-2 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
        {/* Search */}
        <div className="relative w-full md:max-w-md">
          <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
            <span className="material-symbols-outlined text-slate-400">search</span>
          </div>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="block w-full pl-10 pr-3 py-2.5 border-none rounded-lg bg-slate-50 dark:bg-slate-800 text-sm text-slate-900 dark:text-white placeholder-slate-400 focus:ring-2 focus:ring-primary/20 focus:bg-white dark:focus:bg-slate-700 transition-all outline-none"
            placeholder={t('tenant.projects.searchPlaceholder')}
          />
        </div>
        {/* Filters */}
        <div className="flex items-center gap-2 w-full md:w-auto overflow-x-auto pb-2 md:pb-0 px-2 md:px-0">
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider mr-1">
            {t('tenant.projects.filter')}
          </span>
          <button className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-primary/10 text-primary border border-primary/20 text-sm font-medium whitespace-nowrap transition-colors">
            {t('common.status.all')}
            <span className="material-symbols-outlined text-lg">arrow_drop_down</span>
          </button>
          <button className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 text-sm font-medium whitespace-nowrap transition-colors">
            {t('common.stats.owner')}
            <span className="material-symbols-outlined text-lg">arrow_drop_down</span>
          </button>
          <div className="w-px h-6 bg-slate-200 dark:bg-slate-700 mx-1"></div>
          <div className="flex bg-slate-100 dark:bg-slate-800 p-1 rounded-lg">
            <button
              onClick={() => setViewMode('grid')}
              className={`p-1.5 rounded transition-all ${viewMode === 'grid' ? 'bg-white dark:bg-slate-700 text-primary shadow-sm' : 'text-slate-400 hover:text-slate-900 dark:hover:text-white'}`}
            >
              <span className="material-symbols-outlined text-lg block">grid_view</span>
            </button>
            <button
              onClick={() => setViewMode('list')}
              className={`p-1.5 rounded transition-all ${viewMode === 'list' ? 'bg-white dark:bg-slate-700 text-primary shadow-sm' : 'text-slate-400 hover:text-slate-900 dark:hover:text-white'}`}
            >
              <span className="material-symbols-outlined text-lg block">view_list</span>
            </button>
          </div>
        </div>
      </div>

      {/* Projects Grid/List */}
      {isLoading ? (
        <div className="text-center py-10 text-slate-500">{t('tenant.projects.loading')}</div>
      ) : viewMode === 'grid' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {projects.map((project) => (
            <div
              key={project.id}
              className="bg-white dark:bg-surface-dark rounded-xl border border-slate-200 dark:border-slate-800 p-5 shadow-sm hover:shadow-md hover:border-primary/50 transition-all group flex flex-col gap-4"
            >
              <div className="flex justify-between items-start">
                <div className="flex gap-3">
                  <div className="h-10 w-10 rounded-lg bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center text-primary">
                    <span className="material-symbols-outlined">psychology</span>
                  </div>
                  <div>
                    <Link
                      to={`/project/${project.id}`}
                      className="text-base font-bold text-slate-900 dark:text-white group-hover:text-primary transition-colors hover:underline"
                    >
                      {project.name}
                    </Link>
                    <p className="text-xs text-slate-500 font-mono mt-0.5">
                      ID: {project.id.slice(0, 8)}
                    </p>
                  </div>
                </div>
                <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
                  {t('common.status.active')}
                </span>
              </div>
              <div className="space-y-3">
                <div className="flex justify-between items-end text-sm">
                  <span className="text-slate-500">{t('common.stats.usage')}</span>
                  <span className="font-bold text-slate-900 dark:text-white">
                    {formatStorage(project.stats?.storage_used || 0)}
                  </span>
                </div>
                <div className="w-full bg-slate-100 dark:bg-slate-700 rounded-full h-2 overflow-hidden">
                  {/* Placeholder progress bar - 1GB as example reference or just relative to something small */}
                  <div
                    className="bg-primary h-2 rounded-full"
                    style={{
                      width: `${Math.min(((project.stats?.storage_used || 0) / (1024 * 1024 * 1024)) * 100, 100)}%`,
                    }}
                  ></div>
                </div>
                <div className="flex gap-4 pt-1">
                  <div className="flex items-center gap-1.5 text-xs text-slate-500">
                    <span className="material-symbols-outlined text-base">memory</span>
                    {project.stats?.memory_count || 0} {t('common.stats.memories')}
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-slate-500">
                    <span className="material-symbols-outlined text-base">hub</span>
                    {project.stats?.node_count || 0} {t('common.stats.nodes')}
                  </div>
                </div>
              </div>
              <div className="border-t border-slate-100 dark:border-slate-800 pt-4 mt-auto flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="flex -space-x-2">
                    {/* Mock avatars based on count */}
                    <div className="w-8 h-8 rounded-full border-2 border-white dark:border-surface-dark bg-slate-200 flex items-center justify-center text-xs text-slate-500">
                      <span className="material-symbols-outlined text-sm">person</span>
                    </div>
                  </div>
                  <span className="text-xs text-slate-500">
                    {project.stats?.member_count || 1} {t('common.stats.members')}
                  </span>
                </div>
                <div className="flex items-center gap-2 relative">
                  <span className="text-xs text-slate-500">
                    {formatTime(project.stats?.last_active)}
                  </span>
                  <button
                    onClick={(e) => {
                      e.preventDefault();
                      setActiveMenu(activeMenu === project.id ? null : project.id);
                    }}
                    className="p-1 rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 hover:text-slate-900 dark:hover:text-white transition-colors"
                  >
                    <span className="material-symbols-outlined text-lg">more_vert</span>
                  </button>

                  {activeMenu === project.id && (
                    <div className="absolute right-0 bottom-full mb-2 w-48 bg-white dark:bg-slate-800 rounded-lg shadow-xl border border-slate-200 dark:border-slate-700 py-1 z-10">
                      <Link
                        to={`/tenant/${currentTenant.id}/projects/${project.id}/edit`}
                        className="w-full text-left px-4 py-2 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700/50 flex items-center gap-2"
                        onClick={() => setActiveMenu(null)}
                      >
                        <span className="material-symbols-outlined text-lg">edit</span>
                        {t('common.edit')}
                      </Link>
                      <button
                        onClick={(e) => {
                          e.preventDefault();
                          handleDelete(project.id);
                        }}
                        className="w-full text-left px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center gap-2"
                      >
                        <span className="material-symbols-outlined text-lg">delete</span>
                        {t('common.delete')}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}

          {/* New Project Placeholder */}
          <Link
            to={`/tenant/${currentTenant.id}/projects/new`}
            className="bg-slate-50 dark:bg-slate-800/50 rounded-xl border-2 border-dashed border-slate-300 dark:border-slate-700 p-5 flex flex-col items-center justify-center gap-4 hover:border-primary hover:bg-primary/5 transition-all group min-h-[200px]"
          >
            <div className="h-12 w-12 rounded-full bg-white dark:bg-slate-700 shadow-sm flex items-center justify-center text-slate-400 group-hover:text-primary group-hover:scale-110 transition-all">
              <span className="material-symbols-outlined text-2xl">add</span>
            </div>
            <div className="text-center">
              <h3 className="text-sm font-bold text-slate-900 dark:text-white group-hover:text-primary">
                {t('tenant.projects.newProjectCard.title')}
              </h3>
              <p className="text-xs text-slate-500 mt-1">
                {t('tenant.projects.newProjectCard.subtitle')}
              </p>
            </div>
          </Link>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="bg-white dark:bg-surface-dark rounded-xl border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200 dark:border-slate-800">
                <tr>
                  <th className="px-6 py-4 font-semibold text-slate-500 dark:text-slate-400">
                    Project
                  </th>
                  <th className="px-6 py-4 font-semibold text-slate-500 dark:text-slate-400">
                    Status
                  </th>
                  <th className="px-6 py-4 font-semibold text-slate-500 dark:text-slate-400">
                    {t('common.stats.usage')}
                  </th>
                  <th className="px-6 py-4 font-semibold text-slate-500 dark:text-slate-400">
                    {t('common.stats.resources')}
                  </th>
                  <th className="px-6 py-4 font-semibold text-slate-500 dark:text-slate-400">
                    {t('common.stats.members')}
                  </th>
                  <th className="px-6 py-4 font-semibold text-slate-500 dark:text-slate-400">
                    {t('common.stats.lastActive')}
                  </th>
                  <th className="px-6 py-4 font-semibold text-slate-500 dark:text-slate-400"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {projects.map((project) => (
                  <tr
                    key={project.id}
                    className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors group"
                  >
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <div className="h-8 w-8 rounded-lg bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center text-primary">
                          <span className="material-symbols-outlined text-lg">psychology</span>
                        </div>
                        <div>
                          <Link
                            to={`/project/${project.id}`}
                            className="font-bold text-slate-900 dark:text-white hover:text-primary transition-colors"
                          >
                            {project.name}
                          </Link>
                          <p className="text-xs text-slate-500 font-mono mt-0.5">
                            ID: {project.id.slice(0, 8)}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
                        Active
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex flex-col gap-1.5 w-32">
                        <div className="flex justify-between text-xs">
                          <span className="text-slate-500">Storage</span>
                          <span className="font-medium text-slate-900 dark:text-white">
                            {formatStorage(project.stats?.storage_used || 0)}
                          </span>
                        </div>
                        <div className="w-full bg-slate-100 dark:bg-slate-700 rounded-full h-1.5 overflow-hidden">
                          <div
                            className="bg-primary h-1.5 rounded-full"
                            style={{
                              width: `${Math.min(((project.stats?.storage_used || 0) / (1024 * 1024 * 1024)) * 100, 100)}%`,
                            }}
                          ></div>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex flex-col gap-1 text-xs text-slate-500">
                        <div className="flex items-center gap-1.5">
                          <span className="material-symbols-outlined text-sm">memory</span>
                          {project.stats?.memory_count || 0}
                        </div>
                        <div className="flex items-center gap-1.5">
                          <span className="material-symbols-outlined text-sm">hub</span>
                          {project.stats?.node_count || 0}
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <div className="flex -space-x-2">
                          <div className="w-7 h-7 rounded-full border-2 border-white dark:border-surface-dark bg-slate-200 flex items-center justify-center text-xs text-slate-500">
                            <span className="material-symbols-outlined text-sm">person</span>
                          </div>
                        </div>
                        <span className="text-xs text-slate-500">
                          {project.stats?.member_count || 1}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-slate-500">
                      {formatTime(project.stats?.last_active)}
                    </td>
                    <td className="px-6 py-4 text-right">
                      <div className="relative">
                        <button
                          onClick={(e) => {
                            e.preventDefault();
                            setActiveMenu(activeMenu === project.id ? null : project.id);
                          }}
                          className="p-1 rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 hover:text-slate-900 dark:hover:text-white transition-colors"
                        >
                          <span className="material-symbols-outlined text-lg">more_vert</span>
                        </button>
                        {activeMenu === project.id && (
                          <div className="absolute right-0 top-full mt-1 w-48 bg-white dark:bg-slate-800 rounded-lg shadow-xl border border-slate-200 dark:border-slate-700 py-1 z-10">
                            <Link
                              to={`/tenant/${currentTenant.id}/projects/${project.id}/edit`}
                              className="w-full text-left px-4 py-2 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700/50 flex items-center gap-2"
                              onClick={() => setActiveMenu(null)}
                            >
                              <span className="material-symbols-outlined text-lg">edit</span>
                              {t('common.edit')}
                            </Link>
                            <button
                              onClick={(e) => {
                                e.preventDefault();
                                handleDelete(project.id);
                              }}
                              className="w-full text-left px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center gap-2"
                            >
                              <span className="material-symbols-outlined text-lg">delete</span>
                              {t('common.delete')}
                            </button>
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

// Export memoized component with custom comparison (rerender-memo)
// Note: Simple memo without custom comparison since the component uses stores
// The stores already handle selective updates via Zustand selectors
export const ProjectList = memo(ProjectListInner);

ProjectList.displayName = 'ProjectList';
