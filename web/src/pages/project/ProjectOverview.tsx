import React, { useEffect, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, Link, useNavigate } from 'react-router-dom';

import {
  AlertCircle,
  Bot,
  Brain,
  CheckCircle,
  ChevronDown,
  Cloud,
  FileText,
  Film,
  Image as ImageIcon,
  MoreVertical,
  Network,
  RefreshCw,
  Trash2,
  Users,
} from 'lucide-react';

import { useProjectBasePath } from '@/hooks/useProjectBasePath';

import { formatDateOnly } from '@/utils/date';

import { LazyDropdown, Modal, message } from '@/components/ui/lazyAntd';

import { projectAPI, memoryAPI } from '../../services/api';

import type { Project, Memory } from '../../types/memory';

interface ProjectOverviewStats {
  memory_count: number;
  storage_used: number;
  storage_limit: number;
  active_nodes: number;
  collaborators: number;
}

interface DropdownClickInfo {
  key: string;
  domEvent: {
    stopPropagation: () => void;
  };
}

const clampPercent = (value: number): number => Math.max(0, Math.min(100, value));

const formatStorage = (bytes: number) => {
  const gb = bytes / (1024 * 1024 * 1024);
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  const mb = bytes / (1024 * 1024);
  if (mb >= 1) return `${mb.toFixed(1)} MB`;
  const kb = bytes / 1024;
  return `${kb.toFixed(1)} KB`;
};

const readMetadataString = (memory: Memory, key: string): string => {
  const metadataValue: unknown = memory.metadata;
  if (!metadataValue || typeof metadataValue !== 'object') {
    return '';
  }

  const metadata = metadataValue as Record<string, unknown>;
  const value = metadata[key];
  return typeof value === 'string' ? value : '';
};

export const ProjectOverview: React.FC = () => {
  const { t } = useTranslation();
  const { projectId } = useParams();
  const navigate = useNavigate();
  const { projectBasePath, tenantBasePath, tenantId } = useProjectBasePath();
  const [stats, setStats] = useState<ProjectOverviewStats | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const loadRequestRef = useRef(0);

  // Action states
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [memoryToDelete, setMemoryToDelete] = useState<Memory | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      if (projectId) {
        const requestId = loadRequestRef.current + 1;
        loadRequestRef.current = requestId;
        const requestedProjectId = projectId;
        setIsLoading(true);
        setLoadError(null);
        try {
          const requestedTenantId = tenantId ?? requestedProjectId;
          const [statsData, projectData, memoriesData] = await Promise.all([
            projectAPI.getStats(requestedProjectId),
            projectAPI.get(requestedTenantId, requestedProjectId),
            memoryAPI.list(requestedProjectId, { page: 1, page_size: 5 }),
          ]);
          if (loadRequestRef.current !== requestId) return;
          setStats(statsData as ProjectOverviewStats);
          setProject(projectData);
          setMemories(memoriesData.memories);
        } catch (error) {
          if (loadRequestRef.current !== requestId) return;
          console.error('Failed to fetch project data:', error);
          setLoadError(
            error instanceof Error
              ? error.message
              : t('project.overview.loadFailed', {
                  defaultValue: 'Unable to load this project.',
                })
          );
        } finally {
          if (loadRequestRef.current === requestId) {
            setIsLoading(false);
          }
        }
      }
    };
    void fetchData();
    return () => {
      loadRequestRef.current += 1;
    };
  }, [projectId, reloadToken, tenantId, t]);

  const handleReprocess = async (memoryId: string) => {
    if (!projectId) return;
    try {
      await memoryAPI.reprocess(projectId, memoryId);
      message.success(t('common.status.processing_started') || 'Processing started');
      // Optimistic update
      setMemories((prev: Memory[]) =>
        prev.map((m: Memory) => (m.id === memoryId ? { ...m, processing_status: 'PENDING' } : m))
      );
    } catch (error) {
      console.error('Failed to reprocess:', error);
      message.error(t('common.errors.processing_failed') || 'Processing failed');
    }
  };

  const handleDelete = async () => {
    if (!memoryToDelete || !projectId) return;

    setIsDeleting(true);
    try {
      await memoryAPI.delete(projectId, memoryToDelete.id);
      message.success(t('common.status.deleted') || 'Memory deleted');

      // Refresh list
      const memoriesData = await memoryAPI.list(projectId, { page: 1, page_size: 5 });
      setMemories(memoriesData.memories);

      // Refresh stats
      const statsData = await projectAPI.getStats(projectId);
      setStats(statsData as ProjectOverviewStats);

      setDeleteModalOpen(false);
      setMemoryToDelete(null);
    } catch (error) {
      console.error('Failed to delete memory:', error);
      message.error(t('common.errors.delete_failed') || 'Delete failed');
    } finally {
      setIsDeleting(false);
    }
  };

  if (!projectId) {
    return <div className="p-8 text-center text-slate-500">{t('project.overview.not_found')}</div>;
  }

  if (isLoading) {
    return <div className="p-8 text-center text-slate-500">{t('common.loading')}</div>;
  }

  if (loadError || !stats) {
    return (
      <div className="mx-auto flex h-full max-w-xl items-center justify-center px-6 py-10">
        <div
          role="alert"
          className="w-full rounded-md bg-white p-6 shadow-[0_0_0_1px_rgba(0,0,0,0.08)] dark:bg-neutral-950 dark:shadow-[0_0_0_1px_rgba(255,255,255,0.12)]"
        >
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-red-50 text-red-600 dark:bg-red-950/40 dark:text-red-300">
              <AlertCircle size={18} aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="text-base font-semibold text-neutral-950 dark:text-neutral-50">
                {t('project.overview.loadFailed', {
                  defaultValue: 'Unable to load this project',
                })}
              </h2>
              <p className="mt-1 text-sm leading-6 text-neutral-600 dark:text-neutral-400">
                {loadError ||
                  t('project.overview.loadFailedDescription', {
                    defaultValue:
                      'The project may have moved, or your account may not have access.',
                  })}
              </p>
            </div>
          </div>
          <div className="mt-5 flex flex-wrap gap-2">
            <Link
              to={`${tenantBasePath}/projects`}
              className="inline-flex h-9 items-center justify-center rounded-md bg-neutral-950 px-3 text-sm font-medium text-white transition-colors hover:bg-neutral-800 focus:outline-none focus:ring-2 focus:ring-neutral-400 focus:ring-offset-2 dark:bg-neutral-50 dark:text-neutral-950 dark:hover:bg-neutral-200 dark:focus:ring-neutral-600 dark:focus:ring-offset-neutral-950"
            >
              {t('project.overview.backToProjects', {
                defaultValue: 'Back to projects',
              })}
            </Link>
            <button
              type="button"
              onClick={() => {
                setReloadToken((value) => value + 1);
              }}
              className="inline-flex h-9 items-center justify-center rounded-md border border-neutral-200 px-3 text-sm font-medium text-neutral-900 transition-colors hover:bg-neutral-50 focus:outline-none focus:ring-2 focus:ring-neutral-400 focus:ring-offset-2 dark:border-neutral-800 dark:text-neutral-100 dark:hover:bg-neutral-900 dark:focus:ring-neutral-600 dark:focus:ring-offset-neutral-950"
            >
              {t('common.retry')}
            </button>
          </div>
        </div>
      </div>
    );
  }

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000);

    if (diffInSeconds < 60) return t('common.time.justNow');
    if (diffInSeconds < 3600)
      return `${Math.floor(diffInSeconds / 60).toString()}${t('common.time.minutes')} ${t('common.time.ago', { time: '' })}`;
    if (diffInSeconds < 86400)
      return `${Math.floor(diffInSeconds / 3600).toString()}${t('common.time.hours')} ${t('common.time.ago', { time: '' })}`;
    return formatDateOnly(date);
  };

  const getMemoryStatus = (memory: Memory) => {
    if (memory.status === 'DISABLED') {
      return {
        label: t('common.status.unavailable'),
        color: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
        dot: 'bg-red-500',
      };
    }
    return {
      label: t('common.status.available'),
      color: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
      dot: 'bg-green-500',
    };
  };

  const getMemoryTitle = (memory: Memory) => {
    // If title is generic (same as content_type) or empty, generate a better title
    if (
      !memory.title ||
      memory.title === memory.content_type ||
      memory.title === 'description' ||
      memory.title === 'text'
    ) {
      // Use first 50 chars of content as title
      const contentPreview = memory.content || readMetadataString(memory, 'source_content');
      if (contentPreview) {
        return contentPreview.substring(0, 50) + (contentPreview.length > 50 ? '...' : '');
      }
      return t('project.memories.untitled');
    }
    return memory.title;
  };

  const storageQuotaPercent =
    stats.storage_limit > 0 ? clampPercent((stats.storage_used / stats.storage_limit) * 100) : 0;

  return (
    <div className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8">
      <div className="grid gap-6 2xl:grid-cols-[minmax(0,1fr)_336px]">
        <div className="min-w-0 space-y-6">
          <section className="rounded-md bg-white shadow-[0_0_0_1px_rgba(0,0,0,0.08)] dark:bg-neutral-950 dark:shadow-[0_0_0_1px_rgba(255,255,255,0.12)]">
            <div className="grid gap-6 border-b border-neutral-200 px-5 py-5 dark:border-neutral-800 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-start">
              <div className="min-w-0">
                <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-neutral-200 bg-neutral-50 px-2.5 py-1 text-[11px] font-medium uppercase tracking-wide text-neutral-600 dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-[#0070f3]" />
                  {t('project.memories.eyebrow')}
                </div>
                <h2 className="text-3xl font-semibold tracking-[-0.04em] text-neutral-950 dark:text-neutral-50">
                  {t('project.overview.title')}
                </h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-neutral-500 dark:text-neutral-400">
                  {t('project.overview.subtitle', { name: project?.name || 'Project' })}
                </p>
              </div>

              <div className="grid min-w-0 grid-cols-2 gap-2 sm:grid-cols-4 xl:min-w-[520px]">
                <div className="rounded-md border border-neutral-200 bg-neutral-50 p-3 dark:border-neutral-800 dark:bg-neutral-900">
                  <div className="flex items-center justify-between gap-2 text-[11px] font-medium uppercase tracking-wide text-neutral-500">
                    {t('common.stats.totalMemories')}
                    <Brain size={14} className="text-neutral-400" />
                  </div>
                  <div className="mt-3 text-2xl font-semibold tracking-[-0.03em] text-neutral-950 dark:text-neutral-50">
                    {stats.memory_count}
                  </div>
                  <div className="mt-1 text-xs text-neutral-500">
                    {t('project.overview.storedInDb')}
                  </div>
                </div>

                <div className="rounded-md border border-neutral-200 bg-neutral-50 p-3 dark:border-neutral-800 dark:bg-neutral-900">
                  <div className="flex items-center justify-between gap-2 text-[11px] font-medium uppercase tracking-wide text-neutral-500">
                    {t('common.stats.storageUsed')}
                    <Cloud size={14} className="text-neutral-400" />
                  </div>
                  <div className="mt-3 text-2xl font-semibold tracking-[-0.03em] text-neutral-950 dark:text-neutral-50">
                    {formatStorage(stats.storage_used)}
                  </div>
                  <div className="mt-2 h-1 overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-800">
                    <div
                      className="h-full rounded-full bg-neutral-950 dark:bg-neutral-50"
                      style={{ width: `${storageQuotaPercent.toString()}%` }}
                    />
                  </div>
                  <div className="mt-1 text-xs text-neutral-500">
                    {t('project.overview.quotaUsage', {
                      percent: Math.round(storageQuotaPercent),
                    })}
                  </div>
                </div>

                <div className="rounded-md border border-neutral-200 bg-neutral-50 p-3 dark:border-neutral-800 dark:bg-neutral-900">
                  <div className="flex items-center justify-between gap-2 text-[11px] font-medium uppercase tracking-wide text-neutral-500">
                    {t('common.stats.activeNodes')}
                    <Network size={14} className="text-neutral-400" />
                  </div>
                  <div className="mt-3 text-2xl font-semibold tracking-[-0.03em] text-neutral-950 dark:text-neutral-50">
                    {stats.active_nodes}
                  </div>
                  <div className="mt-1 flex items-center gap-1.5 text-xs text-neutral-500">
                    <CheckCircle size={13} className="text-[#0070f3]" />
                    {t('project.overview.operationalStatus')}
                  </div>
                </div>

                <div className="rounded-md border border-neutral-200 bg-neutral-50 p-3 dark:border-neutral-800 dark:bg-neutral-900">
                  <div className="flex items-center justify-between gap-2 text-[11px] font-medium uppercase tracking-wide text-neutral-500">
                    {t('common.stats.collaborators')}
                    <Users size={14} className="text-neutral-400" />
                  </div>
                  <div className="mt-3 text-2xl font-semibold tracking-[-0.03em] text-neutral-950 dark:text-neutral-50">
                    {stats.collaborators}
                  </div>
                  <div className="mt-1 text-xs text-neutral-500">
                    {t('project.overview.projectMembers')}
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section className="overflow-hidden rounded-md bg-white shadow-[0_0_0_1px_rgba(0,0,0,0.08)] dark:bg-neutral-950 dark:shadow-[0_0_0_1px_rgba(255,255,255,0.12)]">
            <div className="flex flex-col gap-3 border-b border-neutral-200 px-5 py-4 dark:border-neutral-800 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-base font-semibold tracking-[-0.02em] text-neutral-950 dark:text-neutral-50">
                  {t('project.overview.activeMemories')}
                </h3>
                <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
                  {t('project.overview.storedInDb')}
                </p>
              </div>
              <Link
                to={`${projectBasePath}/memories`}
                className="inline-flex h-8 items-center justify-center rounded-md border border-neutral-200 px-3 text-sm font-medium text-neutral-900 transition-colors hover:bg-neutral-50 focus:outline-none focus:ring-2 focus:ring-neutral-400 focus:ring-offset-2 dark:border-neutral-800 dark:text-neutral-100 dark:hover:bg-neutral-900 dark:focus:ring-neutral-600 dark:focus:ring-offset-neutral-950"
              >
                {t('common.actions.viewAll')}
              </Link>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-[760px] w-full text-left text-sm">
                <thead className="border-b border-neutral-200 bg-neutral-50 dark:border-neutral-800 dark:bg-neutral-900">
                  <tr>
                    <th className="px-5 py-3 text-[11px] font-medium uppercase tracking-wide text-neutral-500">
                      {t('common.forms.name')}
                    </th>
                    <th className="px-5 py-3 text-[11px] font-medium uppercase tracking-wide text-neutral-500">
                      {t('common.forms.type')}
                    </th>
                    <th className="px-5 py-3 text-[11px] font-medium uppercase tracking-wide text-neutral-500">
                      {t('common.forms.status')}
                    </th>
                    <th className="px-5 py-3 text-right text-[11px] font-medium uppercase tracking-wide text-neutral-500">
                      {t('project.memories.size')}
                    </th>
                    <th className="px-5 py-3 text-[11px] font-medium uppercase tracking-wide text-neutral-500"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
                  {memories.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-5 py-12 text-center text-sm text-neutral-500">
                        {t('project.memories.noMemories')}
                      </td>
                    </tr>
                  ) : (
                    memories.map((memory: Memory) => {
                      const status = getMemoryStatus(memory);
                      const memoryTitle = getMemoryTitle(memory);
                      return (
                        <tr
                          key={memory.id}
                          onClick={() => {
                            void navigate(`${projectBasePath}/memory/${memory.id}`);
                          }}
                          className="group cursor-pointer transition-colors hover:bg-neutral-50 dark:hover:bg-neutral-900"
                        >
                          <td className="px-5 py-3">
                            <div className="flex items-center gap-3">
                              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-neutral-200 bg-white text-neutral-500 dark:border-neutral-800 dark:bg-neutral-950 dark:text-neutral-400">
                                {memory.content_type === 'image' ? (
                                  <ImageIcon size={16} />
                                ) : memory.content_type === 'video' ? (
                                  <Film size={16} />
                                ) : (
                                  <FileText size={16} />
                                )}
                              </div>
                              <div className="min-w-0">
                                <div className="truncate font-medium text-neutral-950 dark:text-neutral-50">
                                  {memoryTitle}
                                </div>
                                <div className="text-xs text-neutral-500">
                                  {t('common.time.updated', {
                                    time: formatDate(memory.updated_at || memory.created_at),
                                  })}
                                </div>
                              </div>
                            </div>
                          </td>
                          <td className="px-5 py-3 capitalize text-neutral-600 dark:text-neutral-300">
                            {memory.content_type}
                          </td>
                          <td className="px-5 py-3">
                            <span
                              className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${status.color}`}
                            >
                              <span className={`w-1.5 h-1.5 rounded-full ${status.dot}`}></span>
                              {status.label}
                            </span>
                          </td>
                          <td className="px-5 py-3 text-right font-mono text-neutral-600 dark:text-neutral-300">
                            {formatStorage(memory.content.length)}
                          </td>
                          <td className="px-5 py-3 text-right">
                            <LazyDropdown
                              menu={{
                                items: [
                                  {
                                    key: 'reprocess',
                                    label: t('common.actions.reprocess') || 'Reprocess',
                                    icon: <RefreshCw size={14} />,
                                  },
                                  {
                                    key: 'delete',
                                    label: t('common.actions.delete') || 'Delete',
                                    danger: true,
                                    icon: <Trash2 size={14} />,
                                  },
                                ],
                                onClick: ({ key, domEvent }: DropdownClickInfo) => {
                                  domEvent.stopPropagation();
                                  if (key === 'reprocess') {
                                    void handleReprocess(memory.id);
                                  }
                                  if (key === 'delete') {
                                    setMemoryToDelete(memory);
                                    setDeleteModalOpen(true);
                                  }
                                },
                              }}
                              trigger={['click']}
                            >
                              <button
                                type="button"
                                aria-label={t('project.memories.openActions', {
                                  name: memoryTitle,
                                })}
                                title={t('project.memories.openActions', {
                                  name: memoryTitle,
                                })}
                                onClick={(e) => {
                                  e.stopPropagation();
                                }}
                                className="rounded-md p-1 text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-950 focus:outline-none focus:ring-2 focus:ring-neutral-400 dark:hover:bg-neutral-800 dark:hover:text-neutral-50"
                              >
                                <MoreVertical size={16} />
                              </button>
                            </LazyDropdown>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
            <div className="flex justify-center border-t border-neutral-200 bg-neutral-50 px-5 py-3 dark:border-neutral-800 dark:bg-neutral-900">
              <Link
                to={`${projectBasePath}/memories`}
                className="flex items-center gap-1 text-xs font-medium text-neutral-500 transition-colors hover:text-neutral-950 dark:hover:text-neutral-50"
              >
                {t('common.actions.showMore')} <ChevronDown size={14} />
              </Link>
            </div>
          </section>
        </div>

        <aside className="grid gap-4 md:grid-cols-2 2xl:flex 2xl:flex-col">
          <section className="rounded-md bg-white p-5 shadow-[0_0_0_1px_rgba(0,0,0,0.08)] dark:bg-neutral-950 dark:shadow-[0_0_0_1px_rgba(255,255,255,0.12)]">
            <div className="mb-5 flex items-center justify-between">
              <h3 className="text-sm font-semibold tracking-[-0.01em] text-neutral-950 dark:text-neutral-50">
                {t('project.overview.projectTeam')}
              </h3>
              <Link
                to={`${projectBasePath}/settings`}
                aria-label={t('project.overview.projectTeam')}
                className="rounded-md p-1 text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-950 focus:outline-none focus:ring-2 focus:ring-neutral-400 dark:hover:bg-neutral-900 dark:hover:text-neutral-50"
              >
                <Users size={16} />
              </Link>
            </div>
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-neutral-950 text-white dark:bg-neutral-50 dark:text-neutral-950">
                <Users size={16} />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium text-neutral-950 dark:text-neutral-50">
                  {stats.collaborators} {t('common.stats.members')}
                </p>
                <p className="mt-0.5 text-xs text-neutral-500">
                  {t('project.overview.collaborating')}
                </p>
              </div>
            </div>
          </section>

          <section className="rounded-md bg-neutral-950 p-5 text-white shadow-[0_0_0_1px_rgba(0,0,0,0.08)] dark:bg-neutral-50 dark:text-neutral-950">
            <div className="mb-5 flex items-center justify-between">
              <h3 className="text-sm font-semibold tracking-[-0.01em]">
                {t('common.stats.systemStatus')}
              </h3>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-2 py-1 text-[11px] font-medium uppercase tracking-wide text-white/80 dark:bg-neutral-950/10 dark:text-neutral-700">
                <span className="h-1.5 w-1.5 rounded-full bg-[#0070f3]" />
                {t('project.overview.operationalStatus')}
              </span>
            </div>
            <div className="flex items-start gap-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-white/10 dark:bg-neutral-950/10">
                <Bot size={16} />
              </div>
              <div>
                <p className="text-sm font-medium">{t('project.overview.autoIndexing')}</p>
                <p className="mt-1 text-xs leading-5 text-white/60 dark:text-neutral-600">
                  {t('project.overview.systemReady')}
                </p>
              </div>
            </div>
            <div className="mt-5">
              <div className="h-1 overflow-hidden rounded-full bg-white/15 dark:bg-neutral-950/15">
                <div className="h-full w-full rounded-full bg-white dark:bg-neutral-950" />
              </div>
              <div className="mt-2 flex justify-between text-[11px] text-white/55 dark:text-neutral-600">
                <span>{t('project.overview.status')}</span>
                <span>{t('project.overview.operational')}</span>
              </div>
            </div>
          </section>
        </aside>
      </div>

      {/* Delete Confirmation Modal */}
      <Modal
        title={t('project.memories.deleteTitle') || 'Delete Memory'}
        open={deleteModalOpen}
        onOk={() => {
          void handleDelete();
        }}
        onCancel={() => {
          setDeleteModalOpen(false);
          setMemoryToDelete(null);
        }}
        okText={t('common.actions.delete') || 'Delete'}
        cancelText={t('common.actions.cancel') || 'Cancel'}
        okButtonProps={{ danger: true, loading: isDeleting }}
      >
        <p>
          {t('project.memories.deleteConfirmation') ||
            'Are you sure you want to delete this memory? This action cannot be undone.'}
        </p>
        {memoryToDelete && (
          <div className="mt-2 p-3 bg-slate-50 dark:bg-slate-800 rounded border border-slate-200 dark:border-slate-700">
            <p className="font-medium text-slate-900 dark:text-white">{memoryToDelete.title}</p>
          </div>
        )}
      </Modal>
    </div>
  );
};
