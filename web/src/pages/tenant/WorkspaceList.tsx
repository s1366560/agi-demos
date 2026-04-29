import { useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';

import { Input, Progress, Spin, Tag } from 'antd';
import { FolderKanban, LayoutGrid, Plus, Search, Target } from 'lucide-react';

import { useCurrentProject, useProjectStore } from '@/stores/project';
import { useCurrentTenant } from '@/stores/tenant';
import { useWorkspaceActions, useWorkspaceLoading, useWorkspaces } from '@/stores/workspace';

import { workspaceObjectiveService, workspaceTaskService } from '@/services/workspaceService';

import { formatDistanceToNow } from '@/utils/date';
import {
  getSandboxCodeRoot,
  getWorkspaceCollaborationMode,
  getWorkspaceUseCase,
} from '@/utils/workspaceConfig';

import { EmptyStateSimple } from '@/components/shared/ui/EmptyStateVariant';

import type {
  CyberObjective,
  WorkspaceCollaborationMode,
  WorkspaceTask,
  WorkspaceUseCase,
} from '@/types/workspace';

type SummarySource = 'objectives' | 'tasks' | 'empty';

interface ObjectiveSummary {
  source: SummarySource;
  total: number;
  objectives: number;
  avgProgress: number;
  completed: number;
  loading: boolean;
}

const EMPTY_SUMMARY: ObjectiveSummary = {
  source: 'empty',
  total: 0,
  objectives: 0,
  avgProgress: 0,
  completed: 0,
  loading: true,
};

// Domain validates CyberObjective.progress in [0.0, 1.0], but some
// UIs send 0-100. Auto-detect scale: if any value > 1, assume the
// collection is on a 0-100 scale; otherwise multiply by 100.
function normaliseProgress(items: CyberObjective[]): number[] {
  const raw = items.map((o) => (Number.isFinite(o.progress) ? o.progress : 0));
  const max = raw.reduce((m, v) => (v > m ? v : m), 0);
  const scale = max > 1 ? 1 : 100;
  return raw.map((v) => Math.max(0, Math.min(100, v * scale)));
}

function summarizeObjectives(items: CyberObjective[]): ObjectiveSummary | null {
  const objectives = items.filter((o) => o.obj_type === 'objective');
  const relevant = objectives.length > 0 ? objectives : items;
  const total = relevant.length;
  if (total === 0) return null;
  const percents = normaliseProgress(relevant);
  const sum = percents.reduce((acc, p) => acc + p, 0);
  const completed = percents.filter((p) => p >= 100).length;
  return {
    source: 'objectives',
    total: items.length,
    objectives: objectives.length,
    avgProgress: Math.round(sum / total),
    completed,
    loading: false,
  };
}

function summarizeTasks(tasks: WorkspaceTask[]): ObjectiveSummary {
  const total = tasks.length;
  if (total === 0) {
    return {
      source: 'empty',
      total: 0,
      objectives: 0,
      avgProgress: 0,
      completed: 0,
      loading: false,
    };
  }
  const completed = tasks.filter((t) => t.status === 'done').length;
  return {
    source: 'tasks',
    total,
    objectives: 0,
    avgProgress: Math.round((completed / total) * 100),
    completed,
    loading: false,
  };
}

export function WorkspaceList() {
  const { t } = useTranslation();
  const params = useParams<{ tenantId?: string; projectId?: string }>();
  const currentTenant = useCurrentTenant();
  const currentProject = useCurrentProject();
  const projects = useProjectStore((state) => state.projects);
  const listProjects = useProjectStore((state) => state.listProjects);
  const workspaces = useWorkspaces();
  const isLoading = useWorkspaceLoading();
  const { loadWorkspaces } = useWorkspaceActions();

  const [query, setQuery] = useState('');
  const [summaries, setSummaries] = useState<Record<string, ObjectiveSummary>>({});

  const tenantId = params.tenantId ?? currentTenant?.id ?? null;
  const projectId = params.projectId ?? currentProject?.id ?? projects[0]?.id ?? null;
  const useCaseLabels = useMemo(
    () =>
      ({
        general: t('tenant.workspaceList.typeGeneral', 'General'),
        programming: t('tenant.workspaceList.typeProgramming', 'Programming'),
        conversation: t('tenant.workspaceList.typeConversation', 'Conversation'),
        research: t('tenant.workspaceList.typeResearch', 'Research'),
        operations: t('tenant.workspaceList.typeOperations', 'Operations'),
      }) satisfies Record<WorkspaceUseCase, string>,
    [t]
  );
  const collaborationModeLabels = useMemo(
    () =>
      ({
        single_agent: t('tenant.workspaceList.modeSingle', 'Single'),
        multi_agent_shared: t('tenant.workspaceList.modeShared', 'Shared team'),
        multi_agent_isolated: t('tenant.workspaceList.modeIsolated', 'Isolated'),
        autonomous: t('tenant.workspaceList.modeAutonomous', 'Autonomous'),
      }) satisfies Record<WorkspaceCollaborationMode, string>,
    [t]
  );
  useEffect(() => {
    if (!tenantId || params.projectId || currentProject || projects.length > 0) return;
    void listProjects(tenantId).catch(() => {
      // ignore and keep empty-state guidance visible
    });
  }, [tenantId, params.projectId, currentProject, projects.length, listProjects]);

  useEffect(() => {
    if (!tenantId || !projectId) return;
    void loadWorkspaces(tenantId, projectId);
  }, [tenantId, projectId, loadWorkspaces]);

  // Fetch objective summaries in parallel for all visible workspaces.
  useEffect(() => {
    if (!tenantId || !projectId || workspaces.length === 0) return;
    let cancelled = false;
    const ids = workspaces.map((w) => w.id);

    void (async () => {
      setSummaries((prev) => {
        const next = { ...prev };
        for (const id of ids) {
          if (!next[id]) next[id] = EMPTY_SUMMARY;
        }
        return next;
      });

      await Promise.all(
        ids.map(async (id) => {
          try {
            const [items, tasks] = await Promise.all([
              workspaceObjectiveService.list(tenantId, projectId, id).catch(() => []),
              workspaceTaskService.list(id).catch(() => []),
            ]);
            if (cancelled) return;
            const fromObjectives = summarizeObjectives(items);
            // Prefer objectives when they exist AND have any progress.
            // Otherwise fall back to task completion rate so cards
            // remain informative for workspaces that rely on tasks only.
            const useObjectives = fromObjectives !== null && fromObjectives.avgProgress > 0;
            const summary = useObjectives
              ? fromObjectives
              : fromObjectives && tasks.length === 0
                ? fromObjectives
                : summarizeTasks(tasks);
            setSummaries((prev) => ({ ...prev, [id]: summary }));
          } catch {
            if (cancelled) return;
            setSummaries((prev) => ({
              ...prev,
              [id]: {
                source: 'empty',
                total: 0,
                objectives: 0,
                avgProgress: 0,
                completed: 0,
                loading: false,
              },
            }));
          }
        })
      );
    })();

    return () => {
      cancelled = true;
    };
  }, [tenantId, projectId, workspaces]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return workspaces;
    return workspaces.filter(
      (w) => w.name.toLowerCase().includes(q) || (w.description?.toLowerCase().includes(q) ?? false)
    );
  }, [workspaces, query]);

  if (!tenantId || !projectId) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center p-6">
        <EmptyStateSimple
          icon={FolderKanban}
          title={t('tenant.workspaceList.noContextTitle', 'Pick a tenant and project')}
          description={t(
            'tenant.workspaceList.noContextDescription',
            'Workspaces are scoped to a project. Select a tenant and project to continue.'
          )}
        />
      </div>
    );
  }

  const totalLabel = t('tenant.workspaceList.count', {
    count: workspaces.length,
    defaultValue: `${String(workspaces.length)} workspaces`,
  });
  const createWorkspacePath =
    tenantId && projectId
      ? `/tenant/${tenantId}/project/${projectId}/workspaces/new`
      : `/tenant/${tenantId}/workspaces/new`;

  return (
    <div className="flex h-full min-h-0 w-full flex-col px-6 py-8 sm:px-8">
      {/* Header */}
      <header className="mb-6 flex flex-col gap-1">
        <div className="flex items-baseline gap-3">
          <h1 className="text-2xl font-semibold tracking-tight text-text-primary dark:text-text-inverse">
            {t('tenant.workspaceList.title', 'Workspaces')}
          </h1>
          {!isLoading && workspaces.length > 0 ? (
            <span className="text-sm text-text-secondary dark:text-text-muted">{totalLabel}</span>
          ) : null}
        </div>
        <p className="text-sm text-text-secondary dark:text-text-muted">
          {t(
            'tenant.workspaceList.subtitle',
            'Collaborative multi-agent spaces scoped to this project'
          )}
        </p>
      </header>

      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="sm:w-80">
          <label className="sr-only" htmlFor="workspace-search-input">
            {t('tenant.workspaceList.searchPlaceholder', 'Search workspaces...')}
          </label>
          <Input
            id="workspace-search-input"
            prefix={<Search size={14} className="text-text-muted" />}
            placeholder={t('tenant.workspaceList.searchPlaceholder', 'Search workspaces...')}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
            }}
            allowClear
          />
        </div>
        <Link
          to={createWorkspacePath}
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-white transition hover:bg-primary/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:text-white"
        >
          <Plus size={14} aria-hidden />
          {t('tenant.workspaceList.createButton', 'Create Workspace')}
        </Link>
      </div>

      {/* Content */}
      <div className="-mx-2 min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {isLoading && workspaces.length === 0 ? (
          <div className="flex min-h-[240px] items-center justify-center">
            <Spin />
          </div>
        ) : filtered.length === 0 ? (
          <EmptyStateSimple
            icon={LayoutGrid}
            title={
              query
                ? t('tenant.workspaceList.emptyFiltered', 'No workspaces match your search')
                : t('tenant.workspaceList.empty', 'No workspaces found')
            }
            description={
              query
                ? undefined
                : t(
                    'tenant.workspaceList.emptyDescription',
                    'Create a workspace to organize your agents and objectives'
                  )
            }
          />
        ) : (
          <ul
            className="grid min-w-0 gap-3"
            style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}
          >
            {filtered.map((workspace) => {
              const updated = workspace.updated_at ?? workspace.created_at;
              const archived = workspace.is_archived === true;
              const summary = summaries[workspace.id];
              const useCase = getWorkspaceUseCase(workspace);
              const collaboration = getWorkspaceCollaborationMode(workspace);
              const codeRoot = getSandboxCodeRoot(workspace);
              return (
                <li key={workspace.id} className="min-w-0 h-full">
                  <Link
                    to={`/tenant/${tenantId}/project/${projectId}/blackboard?workspaceId=${workspace.id}`}
                    aria-label={workspace.name}
                    className="group flex h-full min-w-0 flex-col gap-2 overflow-hidden rounded-md border border-border-light bg-surface-light p-4 transition-colors hover:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 dark:border-border-dark dark:bg-surface-dark"
                  >
                    <div className="flex min-w-0 items-start justify-between gap-2">
                      <h3 className="line-clamp-1 text-[15px] font-medium text-text-primary group-hover:text-primary dark:text-text-inverse">
                        {workspace.name}
                      </h3>
                      {archived ? (
                        <Tag color="default" className="!m-0 flex-shrink-0">
                          {t('tenant.workspaceList.archived', 'Archived')}
                        </Tag>
                      ) : null}
                    </div>
                    <p className="line-clamp-2 min-h-[2.5rem] min-w-0 break-words text-xs text-text-secondary dark:text-text-muted">
                      {workspace.description?.trim() || '—'}
                    </p>
                    <div className="flex min-w-0 flex-wrap gap-1.5">
                      <Tag
                        color={useCase === 'general' ? 'default' : 'blue'}
                        className="!m-0 shrink-0"
                      >
                        {useCaseLabels[useCase]}
                      </Tag>
                      <Tag
                        color={collaboration === 'single_agent' ? 'default' : 'purple'}
                        className="!m-0 shrink-0"
                      >
                        {collaborationModeLabels[collaboration]}
                      </Tag>
                      {codeRoot ? (
                        <Tag
                          color="geekblue"
                          className="!m-0 min-w-0 max-w-full truncate"
                          title={codeRoot}
                        >
                          {codeRoot}
                        </Tag>
                      ) : null}
                    </div>

                    {/* Objective / task progress */}
                    <div
                      className="mt-1 min-w-0 rounded border border-border-light/60 bg-surface-muted px-3 py-2 dark:border-border-dark dark:bg-surface-dark-alt"
                      aria-label={t('tenant.workspaceList.objectiveProgress', 'Objective progress')}
                    >
                      <div className="mb-1 flex items-center justify-between gap-2 text-xs">
                        <span className="flex min-w-0 items-center gap-1.5 text-text-secondary dark:text-text-muted">
                          <Target size={12} aria-hidden />
                          <span className="truncate">
                            {!summary || summary.loading
                              ? t('tenant.workspaceList.loadingObjectives', 'Loading…')
                              : summary.source === 'objectives'
                                ? t('tenant.workspaceList.objectivesCount', {
                                    count:
                                      summary.objectives > 0 ? summary.objectives : summary.total,
                                    defaultValue: `${String(summary.objectives > 0 ? summary.objectives : summary.total)} objectives`,
                                  })
                                : summary.source === 'tasks'
                                  ? t('tenant.workspaceList.tasksCount', {
                                      count: summary.total,
                                      defaultValue: `${String(summary.total)} tasks`,
                                    })
                                  : t('tenant.workspaceList.noObjectives', 'No objectives yet')}
                          </span>
                        </span>
                        <span className="shrink-0 font-medium tabular-nums text-text-primary dark:text-text-inverse">
                          {summary && !summary.loading && summary.source !== 'empty'
                            ? `${String(summary.avgProgress)}%`
                            : '—'}
                        </span>
                      </div>
                      <Progress
                        percent={summary && !summary.loading ? summary.avgProgress : 0}
                        size="small"
                        showInfo={false}
                        {...(summary && !summary.loading && summary.avgProgress >= 100
                          ? { strokeColor: '#10b981' }
                          : {})}
                        aria-hidden
                      />
                      {summary && !summary.loading && summary.source !== 'empty' ? (
                        <div className="mt-1 truncate text-[11px] text-text-muted">
                          {t('tenant.workspaceList.completedCount', {
                            completed: summary.completed,
                            total:
                              summary.source === 'objectives'
                                ? summary.objectives > 0
                                  ? summary.objectives
                                  : summary.total
                                : summary.total,
                            defaultValue: `${String(summary.completed)} of ${String(
                              summary.source === 'objectives'
                                ? summary.objectives > 0
                                  ? summary.objectives
                                  : summary.total
                                : summary.total
                            )} complete`,
                          })}
                        </div>
                      ) : null}
                    </div>

                    <div className="mt-auto flex min-w-0 items-center justify-between gap-2 pt-2 text-xs text-text-muted dark:text-text-muted">
                      <span className="min-w-0 truncate">
                        {t('tenant.workspaceList.updated', {
                          time: formatDistanceToNow(updated),
                          defaultValue: `Updated ${formatDistanceToNow(updated)}`,
                        })}
                      </span>
                      {workspace.office_status ? (
                        <Tag color="default" className="!m-0 shrink-0">
                          {workspace.office_status}
                        </Tag>
                      ) : null}
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
