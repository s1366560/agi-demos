import React, { memo, useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useParams, useSearchParams } from 'react-router-dom';

import {
  Brain,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Database,
  LayoutGrid,
  List,
  MoreVertical,
  Network,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  User,
} from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { confirmAction } from '@/utils/confirmAction';
import { formatDateOnly } from '@/utils/date';
import { logger } from '@/utils/logger';

import { SkeletonLoader } from '@/components/common/SkeletonLoader';
import { LazyAlert, useLazyMessage } from '@/components/ui/lazyAntd';

import { formatStorage } from '../../hooks/useDateFormatter';
import { useDebounce } from '../../hooks/useDebounce';
import { useProjectStore } from '../../stores/project';
import { useTenantStore } from '../../stores/tenant';

import type { TFunction } from 'i18next';

const formatStorageUsagePercent = (bytes: number, maxBytes?: number | null): string => {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0%';
  const fallbackLimit = 1024 * 1024 * 1024;
  const limit =
    typeof maxBytes === 'number' && Number.isFinite(maxBytes) && maxBytes > 0
      ? maxBytes
      : fallbackLimit;
  const percent = Math.min((bytes / limit) * 100, 100);
  return `${String(Math.round(percent * 10) / 10)}%`;
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
      return `${String(Math.floor(diffInSeconds / 60))}${t('common.time.minutes')} ${t('common.time.ago', { time: '' })}`;
    if (diffInSeconds < 86400)
      return `${String(Math.floor(diffInSeconds / 3600))}${t('common.time.hours')} ${t('common.time.ago', { time: '' })}`;
    if (diffInSeconds < 604800)
      return `${String(Math.floor(diffInSeconds / 86400))}${t('common.time.days')} ${t('common.time.ago', { time: '' })}`;
    return formatDateOnly(date);
  };
};

type ProjectListProps = Record<string, never>;
type VisibilityFilter = 'all' | 'public' | 'private';

const DEFAULT_PAGE_SIZE = 20;
const PAGE_SIZE_OPTIONS = [20, 50, 100] as const;

const isVisibilityFilter = (value: string | null): value is VisibilityFilter =>
  value === 'all' || value === 'public' || value === 'private';

const parsePageParam = (value: string | null, fallback: number): number => {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
};

// Use memo to prevent unnecessary re-renders (rerender-memo)
const ProjectListInner: React.FC<ProjectListProps> = () => {
  const { t } = useTranslation();
  const { tenantId: routeTenantId } = useParams<{ tenantId?: string }>();
  const message = useLazyMessage();
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const { listProjects, deleteProject, projects, isLoading, error, total, ownerIds } =
    useProjectStore(
      useShallow((state) => ({
        listProjects: state.listProjects,
        deleteProject: state.deleteProject,
        projects: state.projects,
        isLoading: state.isLoading,
        error: state.error,
        total: state.total,
        ownerIds: state.ownerIds,
      }))
    );
  const tenantId = routeTenantId ?? currentTenant?.id ?? null;
  const tenantBasePath = tenantId ? `/tenant/${tenantId}` : '/tenant';
  const tenantForLimits = currentTenant?.id === tenantId ? currentTenant : null;
  const [searchParams, setSearchParams] = useSearchParams();
  const [search, setSearch] = useState(() => searchParams.get('q') ?? '');
  const [activeMenu, setActiveMenu] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [visibilityFilter, setVisibilityFilter] = useState<VisibilityFilter>(() =>
    isVisibilityFilter(searchParams.get('visibility'))
      ? (searchParams.get('visibility') as VisibilityFilter)
      : 'all'
  );
  const [ownerFilter, setOwnerFilter] = useState(() => searchParams.get('owner') ?? 'all');
  const [page, setPage] = useState(() => parsePageParam(searchParams.get('page'), 1));
  const [pageSize, setPageSize] = useState(() =>
    parsePageParam(searchParams.get('pageSize'), DEFAULT_PAGE_SIZE)
  );
  const debouncedSearch = useDebounce(search, 300);
  const trimmedDebouncedSearch = debouncedSearch.trim();

  // Reflect search/filters/pagination in the URL so views survive reload and sharing
  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    if (trimmedDebouncedSearch) {
      next.set('q', trimmedDebouncedSearch);
    } else {
      next.delete('q');
    }
    if (visibilityFilter !== 'all') {
      next.set('visibility', visibilityFilter);
    } else {
      next.delete('visibility');
    }
    if (ownerFilter !== 'all') {
      next.set('owner', ownerFilter);
    } else {
      next.delete('owner');
    }
    if (page > 1) {
      next.set('page', String(page));
    } else {
      next.delete('page');
    }
    if (pageSize !== DEFAULT_PAGE_SIZE) {
      next.set('pageSize', String(pageSize));
    } else {
      next.delete('pageSize');
    }
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true });
    }
  }, [
    trimmedDebouncedSearch,
    visibilityFilter,
    ownerFilter,
    page,
    pageSize,
    searchParams,
    setSearchParams,
  ]);

  const projectQueryParams = React.useMemo(() => {
    return {
      page,
      page_size: pageSize,
      search: trimmedDebouncedSearch || undefined,
      visibility: visibilityFilter,
      owner_id: ownerFilter === 'all' ? undefined : ownerFilter,
    };
  }, [trimmedDebouncedSearch, ownerFilter, page, pageSize, visibilityFilter]);

  useEffect(() => {
    if (tenantId) {
      // The store records failures in `error` (surfaced below with retry)
      void listProjects(tenantId, projectQueryParams).catch(() => {});
    }
  }, [listProjects, projectQueryParams, tenantId]);

  // Close the row action menu on Escape or outside click
  useEffect(() => {
    if (!activeMenu) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setActiveMenu(null);
      }
    };
    const handlePointerDown = (event: MouseEvent) => {
      if (!(event.target instanceof Element)) return;
      if (!event.target.closest('[data-project-menu-root]')) {
        setActiveMenu(null);
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('mousedown', handlePointerDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('mousedown', handlePointerDown);
    };
  }, [activeMenu]);

  // Create formatTime function using translation hook
  const formatTime = createFormatTime(t);
  const visibilityFilterLabel = t('tenant.projects.filters.visibilityLabel');
  const ownerFilterLabel = t('tenant.projects.filters.ownerLabel');

  const ownerOptions = React.useMemo(
    () =>
      Array.from(new Set([...ownerIds, ...projects.map((project) => project.owner_id)]))
        .filter(Boolean)
        .sort(),
    [ownerIds, projects]
  );

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, totalPages);
  const rangeStart = total === 0 ? 0 : (safePage - 1) * pageSize + 1;
  const rangeEnd = Math.min(total, safePage * pageSize);
  const hasPreviousPage = safePage > 1;
  const hasNextPage = safePage < totalPages;

  const handlePageSizeChange = (nextPageSize: number) => {
    setPageSize(nextPageSize);
    setPage(1);
  };

  const handleRefresh = () => {
    if (!tenantId) return;
    void listProjects(tenantId, projectQueryParams).catch(() => {});
  };

  const handleDelete = async (projectId: string, projectName: string) => {
    if (!tenantId) return;
    if (
      await confirmAction({
        title: t('tenant.projects.deleteConfirm', {
          name: projectName,
          defaultValue: 'Delete project "{{name}}"? This cannot be undone.',
        }),
        danger: true,
      })
    ) {
      try {
        await deleteProject(tenantId, projectId);
        await listProjects(tenantId, projectQueryParams);
        setActiveMenu(null);
      } catch (error) {
        logger.error('Failed to delete project', error);
        message?.error(t('tenant.projects.deleteFailed'));
      }
    }
  };

  if (!tenantId) {
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
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={handleRefresh}
            disabled={isLoading}
            aria-label={t('common.refresh')}
            title={t('common.refresh')}
            className="flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2.5 text-sm font-medium text-slate-700 transition-[color,background-color,border-color,box-shadow,opacity] hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            <RefreshCw size={16} />
          </button>
          <Link
            to={`${tenantBasePath}/backend-stores`}
            className="flex items-center gap-2 rounded-lg border border-slate-300 px-5 py-2.5 text-sm font-medium text-slate-700 transition-[color,background-color,border-color,box-shadow,opacity] hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            <Database size={16} />
            {t('tenant.backendStores.title', { defaultValue: 'Backend stores' })}
          </Link>
          <Link
            to={`${tenantBasePath}/projects/new`}
            className="bg-primary hover:bg-primary-dark text-white px-5 py-2.5 rounded-lg text-sm font-medium shadow-lg shadow-primary/20 flex items-center gap-2 transition-[color,background-color,border-color,box-shadow,opacity]"
          >
            <Plus size={16} />
            {t('tenant.projects.create')}
          </Link>
        </div>
      </div>

      {/* Toolbar: Search & Filters */}
      <div className="flex flex-col md:flex-row gap-4 justify-between items-center bg-white dark:bg-surface-dark p-2 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
        {/* Search */}
        <div className="relative w-full md:max-w-md">
          <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
            <Search size={16} className="text-slate-400" />
          </div>
          <input
            type="text"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className="block w-full pl-10 pr-3 py-2.5 border-none rounded-lg bg-slate-50 dark:bg-slate-800 text-sm text-slate-900 dark:text-white placeholder-slate-400 focus:ring-2 focus:ring-primary/20 focus:bg-white dark:focus:bg-slate-700 transition-[color,background-color,border-color,box-shadow,opacity,transform] outline-none"
            placeholder={t('tenant.projects.searchPlaceholder')}
            aria-label={t('tenant.projects.searchPlaceholder')}
          />
        </div>
        {/* Filters */}
        <div
          data-testid="project-list-filters"
          className="flex w-full flex-wrap items-center gap-2 px-2 pb-1 md:w-auto md:flex-nowrap md:px-0 md:pb-0"
        >
          <span className="mr-1 shrink-0 text-xs font-semibold uppercase tracking-wider text-slate-400">
            {t('tenant.projects.filter')}
          </span>
          <label className="sr-only" htmlFor="project-visibility-filter">
            {visibilityFilterLabel}
          </label>
          <div className="relative shrink-0">
            <select
              id="project-visibility-filter"
              aria-label={visibilityFilterLabel}
              value={visibilityFilter}
              onChange={(event) => {
                setVisibilityFilter(event.target.value as VisibilityFilter);
                setPage(1);
              }}
              className="appearance-none rounded-lg border border-primary/20 bg-primary/10 py-1.5 pl-3 pr-8 text-sm font-medium text-primary transition-colors hover:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/20"
            >
              <option value="all">{t('tenant.projects.filters.allVisibility')}</option>
              <option value="public">{t('tenant.projects.filters.public')}</option>
              <option value="private">{t('tenant.projects.filters.private')}</option>
            </select>
            <ChevronDown
              size={16}
              className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-primary"
            />
          </div>
          <label className="sr-only" htmlFor="project-owner-filter">
            {ownerFilterLabel}
          </label>
          <div className="relative min-w-0 flex-1 sm:flex-none">
            <select
              id="project-owner-filter"
              aria-label={ownerFilterLabel}
              value={ownerFilter}
              onChange={(event) => {
                setOwnerFilter(event.target.value);
                setPage(1);
              }}
              className="w-full max-w-full appearance-none truncate rounded-lg border border-slate-200 bg-white py-1.5 pl-3 pr-8 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-primary/20 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700 sm:w-auto sm:max-w-72"
            >
              <option value="all">{t('tenant.projects.filters.allOwners')}</option>
              {ownerOptions.map((ownerId) => (
                <option key={ownerId} value={ownerId}>
                  {ownerId}
                </option>
              ))}
            </select>
            <ChevronDown
              size={16}
              className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-slate-500"
            />
          </div>
          <div className="mx-1 hidden h-6 w-px bg-slate-200 dark:bg-slate-700 sm:block"></div>
          <div className="flex shrink-0 rounded-lg bg-slate-100 p-1 dark:bg-slate-800">
            <button
              type="button"
              aria-label={t('tenant.projects.viewGrid')}
              title={t('tenant.projects.viewGrid')}
              onClick={() => {
                setViewMode('grid');
              }}
              className={`p-1.5 rounded transition-[color,background-color,border-color,box-shadow,opacity,transform] ${viewMode === 'grid' ? 'bg-white dark:bg-slate-700 text-primary shadow-sm' : 'text-slate-400 hover:text-slate-900 dark:hover:text-white'}`}
            >
              <LayoutGrid size={16} className="block" />
            </button>
            <button
              type="button"
              aria-label={t('tenant.projects.viewList')}
              title={t('tenant.projects.viewList')}
              onClick={() => {
                setViewMode('list');
              }}
              className={`p-1.5 rounded transition-[color,background-color,border-color,box-shadow,opacity,transform] ${viewMode === 'list' ? 'bg-white dark:bg-slate-700 text-primary shadow-sm' : 'text-slate-400 hover:text-slate-900 dark:hover:text-white'}`}
            >
              <List size={16} className="block" />
            </button>
          </div>
        </div>
      </div>

      {/* Load error with retry */}
      {!isLoading && error && (
        <LazyAlert
          type="error"
          showIcon
          title={t('tenant.projects.loadFailed', 'Failed to load projects')}
          description={error}
          action={
            <button
              type="button"
              onClick={handleRefresh}
              className="inline-flex items-center justify-center rounded-md border border-red-300 px-3 py-1 text-sm font-medium text-red-700 transition-colors hover:bg-red-50 dark:border-red-700 dark:text-red-300 dark:hover:bg-red-950/30"
            >
              {t('common.retry')}
            </button>
          }
        />
      )}

      {/* Projects Grid/List */}
      {isLoading ? (
        viewMode === 'grid' ? (
          <SkeletonLoader type="card" count={6} />
        ) : (
          <SkeletonLoader type="table" rows={8} />
        )
      ) : viewMode === 'grid' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {projects.map((project) => (
            <div
              key={project.id}
              className="bg-white dark:bg-surface-dark rounded-xl border border-slate-200 dark:border-slate-800 p-5 shadow-sm hover:shadow-md hover:border-primary/50 transition-[color,background-color,border-color,box-shadow,opacity,transform] group flex flex-col gap-4"
            >
              <div className="flex justify-between items-start">
                <div className="flex gap-3">
                  <div className="h-10 w-10 rounded-lg bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center text-primary">
                    <Brain size={16} />
                  </div>
                  <div>
                    <Link
                      to={`${tenantBasePath}/project/${project.id}`}
                      className="text-base font-bold text-slate-900 dark:text-white group-hover:text-primary transition-colors hover:underline"
                    >
                      {project.name}
                    </Link>
                    <p className="text-xs text-slate-500 font-mono mt-0.5">
                      ID: {project.id.slice(0, 8)}
                    </p>
                  </div>
                </div>
                <span
                  className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold ${
                    project.is_public
                      ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
                      : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
                  }`}
                >
                  {project.is_public
                    ? t('tenant.projects.filters.public')
                    : t('tenant.projects.filters.private')}
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
                  <div
                    className="bg-primary h-2 rounded-full"
                    style={{
                      width: formatStorageUsagePercent(
                        project.stats?.storage_used ?? 0,
                        tenantForLimits?.max_storage
                      ),
                    }}
                  ></div>
                </div>
                <div className="flex gap-4 pt-1">
                  <div className="flex items-center gap-1.5 text-xs text-slate-500">
                    <Brain size={16} />
                    {project.stats?.memory_count || 0} {t('common.stats.memories')}
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-slate-500">
                    <Network size={16} />
                    {project.stats?.node_count || 0} {t('common.stats.nodes')}
                  </div>
                </div>
              </div>
              <div className="border-t border-slate-100 dark:border-slate-800 pt-4 mt-auto flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="flex -space-x-2">
                    <div className="w-8 h-8 rounded-full border-2 border-white dark:border-surface-dark bg-slate-200 flex items-center justify-center text-xs text-slate-500">
                      <User size={14} />
                    </div>
                  </div>
                  <span className="text-xs text-slate-500">
                    {project.stats?.member_count ?? 0} {t('common.stats.members')}
                  </span>
                </div>
                <div className="flex items-center gap-2 relative" data-project-menu-root>
                  <span className="text-xs text-slate-500">
                    {formatTime(project.stats?.last_active)}
                  </span>
                  <button
                    type="button"
                    aria-label={t('tenant.projects.openActions', { name: project.name })}
                    title={t('tenant.projects.openActions', { name: project.name })}
                    aria-haspopup="menu"
                    aria-expanded={activeMenu === project.id}
                    onClick={(e) => {
                      e.preventDefault();
                      setActiveMenu(activeMenu === project.id ? null : project.id);
                    }}
                    className="p-1 rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 hover:text-slate-900 dark:hover:text-white transition-colors"
                  >
                    <MoreVertical size={16} />
                  </button>

                  {activeMenu === project.id && (
                    <div
                      role="menu"
                      className="absolute right-0 bottom-full mb-2 w-48 bg-white dark:bg-slate-800 rounded-lg shadow-lg border border-slate-200 dark:border-slate-700 py-1 z-10"
                    >
                      <Link
                        to={`${tenantBasePath}/projects/${project.id}/edit`}
                        role="menuitem"
                        className="w-full text-left px-4 py-2 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700/50 flex items-center gap-2"
                        onClick={() => {
                          setActiveMenu(null);
                        }}
                      >
                        <Pencil size={16} />
                        {t('common.edit')}
                      </Link>
                      <button
                        type="button"
                        role="menuitem"
                        onClick={(e) => {
                          e.preventDefault();
                          void handleDelete(project.id, project.name);
                        }}
                        className="w-full text-left px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center gap-2"
                      >
                        <Trash2 size={16} />
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
            to={`${tenantBasePath}/projects/new`}
            className="bg-slate-50 dark:bg-slate-800/50 rounded-xl border-2 border-dashed border-slate-300 dark:border-slate-700 p-5 flex flex-col items-center justify-center gap-4 hover:border-primary hover:bg-primary/5 transition-[color,background-color,border-color,box-shadow,opacity] group min-h-50"
          >
            <div className="h-12 w-12 rounded-full bg-white dark:bg-slate-700 shadow-sm flex items-center justify-center text-slate-400 group-hover:text-primary transition-[color,background-color,border-color,box-shadow,opacity]">
              <Plus size={24} />
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
                    {t('tenant.projects.columns.project', { defaultValue: 'Project' })}
                  </th>
                  <th className="px-6 py-4 font-semibold text-slate-500 dark:text-slate-400">
                    {t('tenant.projects.filters.visibilityLabel')}
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
                          <Brain size={16} />
                        </div>
                        <div>
                          <Link
                            to={`${tenantBasePath}/project/${project.id}`}
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
                      <span
                        className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold ${
                          project.is_public
                            ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
                            : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
                        }`}
                      >
                        {project.is_public
                          ? t('tenant.projects.filters.public')
                          : t('tenant.projects.filters.private')}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex flex-col gap-1.5 w-32">
                        <div className="flex justify-between text-xs">
                          <span className="text-slate-500">
                            {t('tenant.projects.storage', { defaultValue: 'Storage' })}
                          </span>
                          <span className="font-medium text-slate-900 dark:text-white">
                            {formatStorage(project.stats?.storage_used || 0)}
                          </span>
                        </div>
                        <div className="w-full bg-slate-100 dark:bg-slate-700 rounded-full h-1.5 overflow-hidden">
                          <div
                            className="bg-primary h-1.5 rounded-full"
                            style={{
                              width: formatStorageUsagePercent(
                                project.stats?.storage_used ?? 0,
                                tenantForLimits?.max_storage
                              ),
                            }}
                          ></div>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex flex-col gap-1 text-xs text-slate-500">
                        <div className="flex items-center gap-1.5">
                          <Brain size={14} />
                          {project.stats?.memory_count || 0}
                        </div>
                        <div className="flex items-center gap-1.5">
                          <Network size={14} />
                          {project.stats?.node_count || 0}
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <div className="flex -space-x-2">
                          <div className="w-7 h-7 rounded-full border-2 border-white dark:border-surface-dark bg-slate-200 flex items-center justify-center text-xs text-slate-500">
                            <User size={14} />
                          </div>
                        </div>
                        <span className="text-xs text-slate-500">
                          {project.stats?.member_count ?? 0}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-slate-500">
                      {formatTime(project.stats?.last_active)}
                    </td>
                    <td className="px-6 py-4 text-right">
                      <div className="relative" data-project-menu-root>
                        <button
                          type="button"
                          aria-label={t('tenant.projects.openActions', { name: project.name })}
                          title={t('tenant.projects.openActions', { name: project.name })}
                          aria-haspopup="menu"
                          aria-expanded={activeMenu === project.id}
                          onClick={(e) => {
                            e.preventDefault();
                            setActiveMenu(activeMenu === project.id ? null : project.id);
                          }}
                          className="p-1 rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 hover:text-slate-900 dark:hover:text-white transition-colors"
                        >
                          <MoreVertical size={16} />
                        </button>
                        {activeMenu === project.id && (
                          <div
                            role="menu"
                            className="absolute right-0 top-full mt-1 w-48 bg-white dark:bg-slate-800 rounded-lg shadow-lg border border-slate-200 dark:border-slate-700 py-1 z-10"
                          >
                            <Link
                              to={`${tenantBasePath}/projects/${project.id}/edit`}
                              role="menuitem"
                              className="w-full text-left px-4 py-2 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700/50 flex items-center gap-2"
                              onClick={() => {
                                setActiveMenu(null);
                              }}
                            >
                              <Pencil size={16} />
                              {t('common.edit')}
                            </Link>
                            <button
                              type="button"
                              role="menuitem"
                              onClick={(e) => {
                                e.preventDefault();
                                void handleDelete(project.id, project.name);
                              }}
                              className="w-full text-left px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center gap-2"
                            >
                              <Trash2 size={16} />
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

      {!isLoading && total > 0 && (
        <div
          className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm dark:border-slate-800 dark:bg-surface-dark sm:flex-row sm:items-center sm:justify-between"
          aria-label={t('common.pagination.label', { defaultValue: 'Pagination' })}
        >
          <div className="text-sm text-slate-500 dark:text-slate-400">
            {t('tenant.projects.pagination.summary', {
              defaultValue: '{{start}}-{{end}} of {{total}} projects',
              start: rangeStart,
              end: rangeEnd,
              total,
            })}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
              <span>{t('tenant.projects.pagination.rowsPerPage')}</span>
              <select
                aria-label={t('tenant.projects.pagination.rowsPerPage')}
                value={pageSize}
                onChange={(event) => {
                  handlePageSizeChange(Number(event.target.value));
                }}
                className="h-8 rounded-md border border-slate-300 bg-white px-2 text-sm text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200"
              >
                {PAGE_SIZE_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              aria-label={t('tenant.projects.pagination.previousPage')}
              disabled={!hasPreviousPage}
              onClick={() => {
                setPage((currentPage) => Math.max(1, currentPage - 1));
              }}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-300 text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
            >
              <ChevronLeft size={16} aria-hidden="true" />
            </button>
            <span className="min-w-20 text-center text-sm text-slate-600 dark:text-slate-300">
              {t('common.pagination.page_info', {
                defaultValue: 'Page {{page}} of {{total}}',
                page: safePage,
                total: totalPages,
              })}
            </span>
            <button
              type="button"
              aria-label={t('tenant.projects.pagination.nextPage')}
              disabled={!hasNextPage}
              onClick={() => {
                setPage((currentPage) => Math.min(totalPages, currentPage + 1));
              }}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-300 text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
            >
              <ChevronRight size={16} aria-hidden="true" />
            </button>
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
