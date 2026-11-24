import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import { Input, Pagination, Progress, Tag } from 'antd';
import { FolderKanban, LayoutGrid, Plus, Search, Target } from 'lucide-react';
import { tokens } from '../../../../../../web/src/theme/tokens';
import { EmptyStateSimple } from '../../../../../../web/src/components/shared/ui/EmptyStateVariant';
import { getSandboxCodeRoot, getWorkspaceCollaborationMode, getWorkspaceUseCase } from '../workspaceConfig';
import type { Workspace, WorkspaceCollaborationMode, WorkspaceUseCase } from '../types/workspace';
type SummarySource = 'objectives' | 'plan' | 'tasks' | 'empty';

export interface ObjectiveSummary {
  source: SummarySource;
  total: number;
  objectives: number;
  avgProgress: number;
  completed: number;
  loading: boolean;
  /** True when every summary source failed to load (distinct from genuinely empty). */
  failed?: boolean;
}

const EMPTY_SUMMARY: ObjectiveSummary = {
  source: 'empty',
  total: 0,
  objectives: 0,
  avgProgress: 0,
  completed: 0,
  loading: true,
};
const WORKSPACE_SUMMARY_BATCH_SIZE = 6;


interface WorkspaceListProps {
  tenantId: string | null;
  projectId: string | null;
  tenantName?: string | undefined;
  projectName?: string | undefined;
  workspaces: Workspace[];
  isLoading: boolean;
  workspaceError: string | null;
  loadWorkspaces: (tenant: string, project: string) => Promise<unknown>;
  loadWorkspaceSummary: (tenant: string, project: string, workspaceId: string) => Promise<ObjectiveSummary>;
  workspacePath: (id: string) => string;
  loadingView: ReactNode;
  extraActions?: ReactNode;
  formatDistanceToNow: (input: string) => string;
}
export function WorkspaceListView({
  tenantId, projectId, tenantName, projectName, workspaces, isLoading, workspaceError,
  loadWorkspaces, loadWorkspaceSummary, workspacePath, loadingView, formatDistanceToNow, extraActions,
}: WorkspaceListProps) {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [query, setQuery] = useState(() => searchParams.get('q') ?? '');
  const [page, setPage] = useState(() => {
    const p = Number(searchParams.get('page'));
    return Number.isInteger(p) && p > 0 ? p : 1;
  });
  const [summaries, setSummaries] = useState<Record<string, ObjectiveSummary>>({});

  // Reflect search/pagination in the URL so views survive reload and sharing
  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    const trimmedQuery = query.trim();
    if (trimmedQuery) {
      next.set('q', trimmedQuery);
    } else {
      next.delete('q');
    }
    if (page > 1) {
      next.set('page', String(page));
    } else {
      next.delete('page');
    }
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true });
    }
  }, [query, page, searchParams, setSearchParams]);

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
    if (!tenantId || !projectId) return;
    // The store records the failure in `error` (surfaced below with retry).
    loadWorkspaces(tenantId, projectId).catch(() => {});
  }, [tenantId, projectId, loadWorkspaces]);

  // Fetch summaries in bounded batches. Default tenants can have many
  // historical workspaces; unbounded fan-out can freeze the browser.
  useEffect(() => {
    if (!tenantId || !projectId || workspaces.length === 0) return;
    const cancellation = { current: false };
    const ids = workspaces.map((w) => w.id);

    void (async () => {
      setSummaries((prev) => {
        const next: Record<string, ObjectiveSummary> = {};
        for (const id of ids) {
          next[id] = prev[id] ?? EMPTY_SUMMARY;
        }
        return next;
      });

      for (let index = 0; index < ids.length; index += WORKSPACE_SUMMARY_BATCH_SIZE) {
        const batchIds = ids.slice(index, index + WORKSPACE_SUMMARY_BATCH_SIZE);
        const batchSummaries = await Promise.all(
          batchIds.map(async (id) => ({
            id,
            summary: await loadWorkspaceSummary(tenantId, projectId, id),
          }))
        );
        if (cancellation.current) return;
        setSummaries((prev) => {
          const next = { ...prev };
          for (const { id, summary } of batchSummaries) {
            next[id] = summary;
          }
          return next;
        });
      }
    })();

    return () => {
      cancellation.current = true;
    };
  }, [tenantId, projectId, workspaces, loadWorkspaceSummary]);

  // Reload a single workspace summary after a failure (per-card retry)
  const retrySummary = useCallback(
    (workspaceId: string) => {
      if (!tenantId || !projectId) return;
      setSummaries((prev) => ({ ...prev, [workspaceId]: EMPTY_SUMMARY }));
      void loadWorkspaceSummary(tenantId, projectId, workspaceId).then((summary) => {
        setSummaries((prev) => ({ ...prev, [workspaceId]: summary }));
      });
    },
    [tenantId, projectId, loadWorkspaceSummary]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return workspaces;
    return workspaces.filter(
      (w) => w.name.toLowerCase().includes(q) || (w.description?.toLowerCase().includes(q) ?? false)
    );
  }, [workspaces, query]);

  const WORKSPACES_PAGE_SIZE = 24;
  const totalWorkspacePages = Math.max(1, Math.ceil(filtered.length / WORKSPACES_PAGE_SIZE));
  const safeWorkspacePage = Math.min(page, totalWorkspacePages);
  const pagedWorkspaces = filtered.slice(
    (safeWorkspacePage - 1) * WORKSPACES_PAGE_SIZE,
    safeWorkspacePage * WORKSPACES_PAGE_SIZE
  );

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
        {tenantName ? (
          <p className="text-xs font-medium uppercase tracking-wider text-text-muted dark:text-text-muted">
            {[tenantName, projectName].filter(Boolean).join(' / ')}
          </p>
        ) : null}
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
            {t('tenant.workspaceList.searchPlaceholder', 'Search workspaces…')}
          </label>
          <Input
            id="workspace-search-input"
            prefix={<Search size={14} className="text-text-muted" />}
            placeholder={t('tenant.workspaceList.searchPlaceholder', 'Search workspaces…')}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(1);
            }}
            allowClear
          />
        </div>
        {extraActions}
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
          loadingView
        ) : workspaceError && workspaces.length === 0 ? (
          <div
            className="flex min-h-[240px] flex-col items-center justify-center gap-3"
            role="alert"
          >
            <p className="text-sm text-text-secondary dark:text-text-muted">{workspaceError}</p>
            <button
              type="button"
              onClick={() => {
                if (!tenantId || !projectId) return;
                loadWorkspaces(tenantId, projectId).catch(() => {});
              }}
              className="rounded-md border border-border-light px-4 py-2 text-sm font-medium text-text-primary transition hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 dark:border-border-dark dark:text-text-inverse"
            >
              {t('common.retry')}
            </button>
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
          <>
            <ul
              className="grid min-w-0 gap-3"
              style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}
            >
              {pagedWorkspaces.map((workspace) => {
                const updated = workspace.updated_at ?? workspace.created_at;
                const archived = workspace.is_archived === true;
                const summary = summaries[workspace.id];
                const useCase = getWorkspaceUseCase(workspace);
                const collaboration = getWorkspaceCollaborationMode(workspace);
                const codeRoot = getSandboxCodeRoot(workspace);
                return (
                  <li key={workspace.id} className="min-w-0 h-full">
                    <Link
                      to={workspacePath(workspace.id)}
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
                        aria-label={t(
                          'tenant.workspaceList.objectiveProgress',
                          'Objective progress'
                        )}
                      >
                        <div className="mb-1 flex items-center justify-between gap-2 text-xs">
                          <span className="flex min-w-0 items-center gap-1.5 text-text-secondary dark:text-text-muted">
                            <Target size={12} aria-hidden />
                            <span
                              className={`truncate ${
                                summary?.failed ? 'text-amber-600 dark:text-amber-400' : ''
                              }`}
                            >
                              {!summary || summary.loading
                                ? t('tenant.workspaceList.loadingObjectives', 'Loading…')
                                : summary.failed
                                  ? t(
                                      'tenant.workspaceList.progressLoadFailed',
                                      'Progress unavailable'
                                    )
                                  : summary.source === 'objectives'
                                    ? t('tenant.workspaceList.objectivesCount', {
                                        count:
                                          summary.objectives > 0
                                            ? summary.objectives
                                            : summary.total,
                                        defaultValue: `${String(summary.objectives > 0 ? summary.objectives : summary.total)} objectives`,
                                      })
                                    : summary.source === 'plan' || summary.source === 'tasks'
                                      ? t('tenant.workspaceList.tasksCount', {
                                          count: summary.total,
                                          defaultValue: `${String(summary.total)} tasks`,
                                        })
                                      : t('tenant.workspaceList.noObjectives', 'No objectives yet')}
                            </span>
                          </span>
                          <span className="shrink-0 font-medium tabular-nums text-text-primary dark:text-text-inverse">
                            {summary?.failed ? (
                              <button
                                type="button"
                                onClick={(event) => {
                                  event.preventDefault();
                                  event.stopPropagation();
                                  retrySummary(workspace.id);
                                }}
                                className="rounded text-xs font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                              >
                                {t('common.retry')}
                              </button>
                            ) : summary && !summary.loading && summary.source !== 'empty' ? (
                              `${String(summary.avgProgress)}%`
                            ) : (
                              '—'
                            )}
                          </span>
                        </div>
                        <Progress
                          percent={summary && !summary.loading ? summary.avgProgress : 0}
                          size="small"
                          showInfo={false}
                          {...(summary && !summary.loading && summary.avgProgress >= 100
                            ? { strokeColor: tokens.status.success }
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
                            {t(
                              `tenant.workspaceList.officeStatus.${workspace.office_status}`,
                              workspace.office_status
                            )}
                          </Tag>
                        ) : null}
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ul>
            {filtered.length > WORKSPACES_PAGE_SIZE ? (
              <div className="mt-4 flex justify-end">
                <Pagination
                  current={safeWorkspacePage}
                  pageSize={WORKSPACES_PAGE_SIZE}
                  total={filtered.length}
                  showSizeChanger={false}
                  onChange={(nextPage) => {
                    setPage(nextPage);
                  }}
                />
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
