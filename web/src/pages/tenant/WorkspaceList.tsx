import { useEffect, useMemo, useState, type FormEvent } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';

import { Button, Input, message, Spin, Tag } from 'antd';
import { FolderKanban, LayoutGrid, Plus, Search } from 'lucide-react';

import { formatDistanceToNow } from '@/utils/date';

import { useCurrentProject, useProjectStore } from '@/stores/project';
import { useCurrentTenant } from '@/stores/tenant';
import { useWorkspaceActions, useWorkspaceLoading, useWorkspaces } from '@/stores/workspace';

import { EmptyStateSimple } from '@/components/shared/ui/EmptyStateVariant';

export function WorkspaceList() {
  const { t } = useTranslation();
  const params = useParams<{ tenantId?: string; projectId?: string }>();
  const currentTenant = useCurrentTenant();
  const currentProject = useCurrentProject();
  const projects = useProjectStore((state) => state.projects);
  const listProjects = useProjectStore((state) => state.listProjects);
  const workspaces = useWorkspaces();
  const isLoading = useWorkspaceLoading();
  const { loadWorkspaces, createWorkspace } = useWorkspaceActions();

  const [name, setName] = useState('');
  const [query, setQuery] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const tenantId = params.tenantId ?? currentTenant?.id ?? null;
  const projectId = params.projectId ?? currentProject?.id ?? projects[0]?.id ?? null;

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

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return workspaces;
    return workspaces.filter(
      (w) =>
        w.name.toLowerCase().includes(q) ||
        (w.description?.toLowerCase().includes(q) ?? false)
    );
  }, [workspaces, query]);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!tenantId || !projectId || !trimmed || submitting) return;
    setSubmitting(true);
    try {
      await createWorkspace(tenantId, projectId, { name: trimmed });
      setName('');
      message.success(t('tenant.workspaceList.createSuccess', 'Workspace created'));
    } catch {
      message.error(t('tenant.workspaceList.createError', 'Failed to create workspace'));
    } finally {
      setSubmitting(false);
    }
  };

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

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-8 sm:px-8">
      {/* Header */}
      <header className="mb-6 flex flex-col gap-1">
        <div className="flex items-baseline gap-3">
          <h1 className="text-2xl font-semibold tracking-tight text-text-primary dark:text-text-inverse">
            {t('tenant.workspaceList.title', 'Workspaces')}
          </h1>
          {!isLoading && workspaces.length > 0 ? (
            <span className="text-sm text-text-secondary dark:text-text-muted">
              {totalLabel}
            </span>
          ) : null}
        </div>
        <p className="text-sm text-text-secondary dark:text-text-muted">
          {t(
            'tenant.workspaceList.subtitle',
            'Collaborative multi-agent spaces scoped to this project'
          )}
        </p>
      </header>

      {/* Toolbar: create form + search */}
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <form onSubmit={(e) => void onSubmit(e)} className="flex flex-1 gap-2 sm:max-w-md">
          <label className="sr-only" htmlFor="workspace-name-input">
            {t('tenant.workspaceList.namePlaceholder', 'Workspace name')}
          </label>
          <Input
            id="workspace-name-input"
            placeholder={t('tenant.workspaceList.namePlaceholder', 'Workspace name')}
            value={name}
            onChange={(e) => {
              setName(e.target.value);
            }}
            maxLength={120}
            disabled={submitting}
            className="flex-1"
          />
          <Button
            type="primary"
            htmlType="submit"
            icon={<Plus size={14} />}
            loading={submitting}
            disabled={!name.trim()}
          >
            {t('tenant.workspaceList.createButton', 'Create Workspace')}
          </Button>
        </form>
        <div className="sm:w-64">
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
      </div>

      {/* Content */}
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
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((workspace) => {
            const updated = workspace.updated_at ?? workspace.created_at;
            const archived = workspace.is_archived === true;
            return (
              <li key={workspace.id}>
                <Link
                  to={`/tenant/${tenantId}/project/${projectId}/blackboard?workspaceId=${workspace.id}`}
                  aria-label={workspace.name}
                  className="group flex h-full flex-col gap-2 rounded-md border border-border-light bg-surface-light p-4 transition-colors hover:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 dark:border-border-dark dark:bg-surface-dark"
                >
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="line-clamp-1 text-[15px] font-medium text-text-primary group-hover:text-primary dark:text-text-inverse">
                      {workspace.name}
                    </h3>
                    {archived ? (
                      <Tag color="default" className="!m-0 flex-shrink-0">
                        {t('tenant.workspaceList.archived', 'Archived')}
                      </Tag>
                    ) : null}
                  </div>
                  <p className="line-clamp-2 min-h-[2.5rem] text-xs text-text-secondary dark:text-text-muted">
                    {workspace.description?.trim() || '—'}
                  </p>
                  <div className="mt-auto flex items-center justify-between pt-2 text-xs text-text-muted dark:text-text-muted">
                    <span>
                      {t('tenant.workspaceList.updated', {
                        time: formatDistanceToNow(updated),
                        defaultValue: `Updated ${formatDistanceToNow(updated)}`,
                      })}
                    </span>
                    {workspace.office_status ? (
                      <Tag color="default" className="!m-0">
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
  );
}
