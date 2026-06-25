import { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useLocation, useParams } from 'react-router-dom';

import {
  Badge,
  Card,
  Dropdown,
  message,
  Modal,
  Pagination,
  Spin,
  Switch,
  Tag,
  Tooltip,
} from 'antd';
import { Bot, Edit2, Eye, MoreVertical, Plus, RefreshCw, Search, Trash2 } from 'lucide-react';

import { AgentDefinitionModal } from '../../components/agent/AgentDefinitionModal';
import {
  useClearDefinitionError,
  useDefinitionError,
  useDefinitionLoading,
  useDefinitionPagination,
  useDefinitions,
  useDeleteDefinition,
  useEnabledDefinitionsCount,
  useListDefinitionsPage,
  useSetDefinitionFilters,
  useToggleDefinitionEnabled,
} from '../../stores/agentDefinitions';
import { useUser } from '../../stores/auth';
import { useProjectStore } from '../../stores/project';
import { useCurrentTenant } from '../../stores/tenant';

import type { AgentDefinition } from '../../types/multiAgent';
import type { MenuProps } from 'antd';

type StatusFilter = 'all' | 'enabled' | 'disabled';
type ScopeFilter = string;
type SortField = 'name' | 'recent' | 'invocations';

function canManageTenantAgents(
  user: ReturnType<typeof useUser>,
  tenant: ReturnType<typeof useCurrentTenant>
): boolean {
  const roles = new Set((user?.roles ?? []).map((role) => role.toLowerCase()));
  return (
    roles.has('admin') ||
    roles.has('owner') ||
    roles.has('system_admin') ||
    tenant?.owner_id === user?.id
  );
}

export const AgentDefinitions: React.FC = () => {
  const { t } = useTranslation();
  const location = useLocation();
  const { tenantId: routeTenantId } = useParams<{ tenantId?: string }>();

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [scopeFilter, setScopeFilter] = useState<ScopeFilter>('all');
  const [sortField, setSortField] = useState<SortField>('name');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingDef, setEditingDef] = useState<AgentDefinition | null>(null);
  const [createProjectId, setCreateProjectId] = useState<string | null>(null);

  const user = useUser();
  const currentTenant = useCurrentTenant();
  const tenantId = routeTenantId ?? currentTenant?.id ?? null;
  const tenantForPermissions = currentTenant?.id === tenantId ? currentTenant : null;
  const projects = useProjectStore((state) => state.projects);
  const listProjects = useProjectStore((state) => state.listProjects);
  const definitions = useDefinitions();
  const isLoading = useDefinitionLoading();
  const error = useDefinitionError();
  const enabledCount = useEnabledDefinitionsCount();
  const { total, page, pageSize } = useDefinitionPagination();

  const listDefinitionsPage = useListDefinitionsPage();
  const deleteDefinition = useDeleteDefinition();
  const toggleEnabled = useToggleDefinitionEnabled();
  const setFilters = useSetDefinitionFilters();
  const clearError = useClearDefinitionError();
  const canManageAgents = canManageTenantAgents(user, tenantForPermissions);

  const projectNameById = useMemo(
    () => new Map(projects.map((project) => [project.id, project.name])),
    [projects]
  );
  const projectScopeOptions = useMemo(() => {
    const ids = new Set<string>();
    for (const project of projects) {
      ids.add(project.id);
    }
    for (const definition of definitions) {
      if (definition.project_id) {
        ids.add(definition.project_id);
      }
    }
    return [...ids].map((id) => ({
      id,
      name: projectNameById.get(id) ?? id,
    }));
  }, [definitions, projectNameById, projects]);
  const tenantDefinitionCount = useMemo(
    () => definitions.filter((definition) => definition.project_id === null).length,
    [definitions]
  );
  const projectDefinitionCount = definitions.length - tenantDefinitionCount;
  const hasActiveFilters = search.trim() !== '' || statusFilter !== 'all' || scopeFilter !== 'all';

  const selectedProjectId = scopeFilter !== 'all' && scopeFilter !== 'tenant' ? scopeFilter : null;

  const listPath = useMemo(() => {
    const segments = location.pathname.split('/').filter(Boolean);
    const definitionsIndex = segments.lastIndexOf('agent-definitions');

    if (definitionsIndex === -1) {
      return '/tenant/agent-definitions';
    }

    return `/${segments.slice(0, definitionsIndex + 1).join('/')}`;
  }, [location.pathname]);

  const loadDefinitionsPage = useCallback(
    (options?: { page?: number; pageSize?: number }) => {
      if (!tenantId) {
        return Promise.resolve();
      }
      const nextPage = options?.page ?? 1;
      const nextPageSize = options?.pageSize ?? pageSize;
      return listDefinitionsPage({
        tenant_id: tenantId,
        project_id: selectedProjectId,
        scope: scopeFilter === 'tenant' ? 'tenant' : undefined,
        search: search.trim() || undefined,
        sort: sortField,
        enabled: statusFilter === 'all' ? undefined : statusFilter === 'enabled',
        limit: nextPageSize,
        offset: Math.max(nextPage - 1, 0) * nextPageSize,
      });
    },
    [
      listDefinitionsPage,
      pageSize,
      scopeFilter,
      search,
      selectedProjectId,
      sortField,
      statusFilter,
      tenantId,
    ]
  );

  const getScopeLabel = useCallback(
    (projectId: string | null): string =>
      projectId
        ? (projectNameById.get(projectId) ?? projectId)
        : t('tenant.agentDefinitions.scope.tenant', { defaultValue: 'Tenant scope' }),
    [projectNameById, t]
  );

  useEffect(() => {
    void loadDefinitionsPage({ page: 1 });
  }, [loadDefinitionsPage]);

  useEffect(() => {
    if (!tenantId) {
      return;
    }
    void listProjects(tenantId, { page_size: 100 }).catch(() => {
      message.error(
        t('tenant.agentDefinitions.messages.projectsLoadFailed', {
          defaultValue: 'Failed to load projects',
        })
      );
    });
  }, [listProjects, tenantId, t]);

  useEffect(() => {
    setFilters({
      search,
      enabled: statusFilter === 'all' ? null : statusFilter === 'enabled',
      projectId: selectedProjectId,
    });
  }, [search, selectedProjectId, statusFilter, setFilters]);

  useEffect(() => {
    if (error) message.error(error);
  }, [error]);

  useEffect(
    () => () => {
      clearError();
    },
    [clearError]
  );

  const handleCreate = useCallback(() => {
    setEditingDef(null);
    setCreateProjectId(scopeFilter !== 'all' && scopeFilter !== 'tenant' ? scopeFilter : null);
    setIsModalOpen(true);
  }, [scopeFilter]);

  const handleEdit = useCallback((def: AgentDefinition) => {
    setEditingDef(def);
    setCreateProjectId(null);
    setIsModalOpen(true);
  }, []);

  const handleToggle = useCallback(
    async (id: string, enabled: boolean) => {
      if (!tenantId) {
        return;
      }
      try {
        await toggleEnabled(id, enabled, { tenant_id: tenantId });
        message.success(
          enabled
            ? t('tenant.agentDefinitions.messages.enabled', { defaultValue: 'Agent enabled' })
            : t('tenant.agentDefinitions.messages.disabled', { defaultValue: 'Agent disabled' })
        );
        void loadDefinitionsPage({ page });
      } catch {
        // Error handled by store
      }
    },
    [loadDefinitionsPage, page, tenantId, toggleEnabled, t]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      if (!tenantId) {
        return;
      }
      try {
        await deleteDefinition(id, { tenant_id: tenantId });
        message.success(
          t('tenant.agentDefinitions.messages.deleted', {
            defaultValue: 'Agent definition deleted',
          })
        );
        const nextPage = definitions.length <= 1 && page > 1 ? page - 1 : page;
        void loadDefinitionsPage({ page: nextPage });
      } catch {
        // Error handled by store
      }
    },
    [definitions.length, deleteDefinition, loadDefinitionsPage, page, tenantId, t]
  );

  const handleRefresh = useCallback(() => {
    void loadDefinitionsPage({ page });
  }, [loadDefinitionsPage, page]);

  const handleModalClose = useCallback(() => {
    setIsModalOpen(false);
    setEditingDef(null);
    setCreateProjectId(null);
  }, []);

  const handleModalSuccess = useCallback(() => {
    setIsModalOpen(false);
    setEditingDef(null);
    setCreateProjectId(null);
    void loadDefinitionsPage({ page: 1 });
  }, [loadDefinitionsPage]);

  const confirmDelete = useCallback(
    (def: AgentDefinition) => {
      Modal.confirm({
        title: t('tenant.agentDefinitions.deleteConfirm.title', {
          name: def.display_name ?? def.name,
          defaultValue: 'Delete {{name}}?',
        }),
        content: t('tenant.agentDefinitions.deleteConfirm.content', {
          defaultValue: 'This removes the agent definition and cannot be undone.',
        }),
        okText: t('common.delete', 'Delete'),
        okType: 'danger',
        cancelText: t('common.cancel', 'Cancel'),
        onOk: async () => {
          await handleDelete(def.id);
        },
      });
    },
    [handleDelete, t]
  );

  const getCardMenuItems = useCallback(
    (def: AgentDefinition): MenuProps['items'] => {
      const items: MenuProps['items'] = [
        {
          key: 'details',
          label: (
            <Link to={`${listPath}/${def.id}`}>
              {t('tenant.agentDefinitions.detail.viewDetails', { defaultValue: 'View details' })}
            </Link>
          ),
          icon: <Eye size={14} />,
        },
      ];

      if (canManageAgents && def.source !== 'builtin') {
        items.push(
          {
            key: 'edit',
            label: t('common.edit', 'Edit'),
            icon: <Edit2 size={14} />,
            onClick: () => {
              handleEdit(def);
            },
          },
          { type: 'divider' },
          {
            key: 'delete',
            label: t('common.delete', 'Delete'),
            icon: <Trash2 size={14} />,
            danger: true,
            onClick: () => {
              confirmDelete(def);
            },
          }
        );
      }

      return items;
    },
    [canManageAgents, confirmDelete, handleEdit, listPath, t]
  );

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-5 p-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            {t('tenant.agentDefinitions.title', 'Agent Definitions')}
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            {t(
              'tenant.agentDefinitions.subtitle',
              'Configure and manage AI agent definitions for your tenant'
            )}
          </p>
        </div>
        {canManageAgents ? (
          <button
            type="button"
            onClick={handleCreate}
            className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-white text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors"
          >
            <Plus size={16} />
            {t('tenant.agentDefinitions.createNew', 'Create Agent')}
          </button>
        ) : null}
      </div>

      {/* Stats bar */}
      <div className="flex items-center gap-4 text-sm text-slate-600 dark:text-slate-400">
        <span>
          {t('tenant.agentDefinitions.stats.agents', {
            count: total,
            defaultValue: '{{count}} agents',
          })}
        </span>
        <span className="text-slate-300 dark:text-slate-600">|</span>
        <span>
          {t('tenant.agentDefinitions.stats.enabled', {
            count: enabledCount,
            defaultValue: '{{count}} enabled',
          })}
        </span>
        <span className="text-slate-300 dark:text-slate-600">|</span>
        <span>
          {t('tenant.agentDefinitions.stats.tenantScoped', {
            count: tenantDefinitionCount,
            defaultValue: '{{count}} tenant',
          })}
        </span>
        <span className="text-slate-300 dark:text-slate-600">|</span>
        <span>
          {t('tenant.agentDefinitions.stats.projectScoped', {
            count: projectDefinitionCount,
            defaultValue: '{{count}} project',
          })}
        </span>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
          <input
            type="text"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
            }}
            aria-label={t('common.search', 'Search...')}
            placeholder={t('common.search', 'Search...')}
            className="w-full pl-9 pr-3 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-text-inverse focus:ring-2 focus:ring-primary/30 focus:border-primary outline-none"
          />
        </div>

        <div className="flex items-center gap-2">
          {(['all', 'enabled', 'disabled'] as StatusFilter[]).map((sf) => (
            <button
              key={sf}
              type="button"
              onClick={() => {
                setStatusFilter(sf);
              }}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                statusFilter === sf
                  ? 'bg-primary text-white'
                  : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600'
              }`}
            >
              {t(`tenant.agentDefinitions.filters.${sf}`, {
                defaultValue: sf.charAt(0).toUpperCase() + sf.slice(1),
              })}
            </button>
          ))}
        </div>

        <select
          aria-label={t('tenant.agentDefinitions.scopeFilter.label', {
            defaultValue: 'Filter by scope',
          })}
          value={scopeFilter}
          onChange={(e) => {
            setScopeFilter(e.target.value);
          }}
          className="px-3 py-1.5 text-xs border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300"
        >
          <option value="all">
            {t('tenant.agentDefinitions.scopeFilter.all', { defaultValue: 'All scopes' })}
          </option>
          <option value="tenant">
            {t('tenant.agentDefinitions.scope.tenant', { defaultValue: 'Tenant scope' })}
          </option>
          {projectScopeOptions.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>

        <select
          aria-label={t('tenant.agentDefinitions.sort.label', {
            defaultValue: 'Sort agent definitions',
          })}
          value={sortField}
          onChange={(e) => {
            setSortField(e.target.value as SortField);
          }}
          className="px-3 py-1.5 text-xs border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300"
        >
          <option value="name">
            {t('tenant.agentDefinitions.sort.name', { defaultValue: 'Name' })}
          </option>
          <option value="recent">
            {t('tenant.agentDefinitions.sort.recent', { defaultValue: 'Recent' })}
          </option>
          <option value="invocations">
            {t('tenant.agentDefinitions.sort.invocations', { defaultValue: 'Invocations' })}
          </option>
        </select>

        <button
          type="button"
          onClick={handleRefresh}
          aria-label={t('tenant.agentDefinitions.refresh', {
            defaultValue: 'Refresh agent definitions',
          })}
          title={t('tenant.agentDefinitions.refresh', {
            defaultValue: 'Refresh agent definitions',
          })}
          className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
        >
          <RefreshCw size={16} />
        </button>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Spin size="large" />
        </div>
      ) : definitions.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-slate-500 dark:text-slate-400">
          <Bot size={48} className="mb-4 text-slate-300 dark:text-slate-600" />
          <p className="text-lg font-medium">
            {hasActiveFilters
              ? t('tenant.agentDefinitions.noResults', 'No agents match your filters')
              : t('tenant.agentDefinitions.empty', 'No agent definitions yet')}
          </p>
          {!hasActiveFilters && canManageAgents && (
            <button
              type="button"
              onClick={handleCreate}
              className="mt-4 text-primary hover:underline text-sm"
            >
              {t('tenant.agentDefinitions.createFirst', 'Create your first agent')}
            </button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {definitions.map((def) => (
            <Card
              key={def.id}
              size="small"
              className="hover:shadow-md transition-shadow dark:bg-slate-800 dark:border-slate-700"
              title={
                <div className="flex items-center gap-2 min-w-0">
                  <Badge status={def.enabled ? 'success' : 'default'} className="flex-shrink-0" />
                  <Tooltip title={def.display_name ?? def.name}>
                    <Link
                      to={`${listPath}/${def.id}`}
                      className="truncate font-medium text-sm text-slate-900 transition-colors hover:text-primary dark:text-white"
                    >
                      {def.display_name ?? def.name}
                    </Link>
                  </Tooltip>
                </div>
              }
              extra={
                <div className="flex items-center gap-2">
                  {canManageAgents && def.source !== 'builtin' ? (
                    <Switch
                      size="small"
                      checked={def.enabled}
                      aria-label={t('tenant.agentDefinitions.toggleAgent', {
                        name: def.display_name ?? def.name,
                        defaultValue: 'Toggle {{name}}',
                      })}
                      onChange={(checked) => {
                        void handleToggle(def.id, checked);
                      }}
                    />
                  ) : (
                    <Tag className="m-0 text-2xs">
                      {t('common.readOnly', { defaultValue: 'Read-only' })}
                    </Tag>
                  )}
                  <Dropdown menu={{ items: getCardMenuItems(def) ?? [] }} trigger={['click']}>
                    <button
                      type="button"
                      aria-label={t('tenant.agentDefinitions.openActions', {
                        name: def.display_name ?? def.name,
                        defaultValue: 'Open actions for {{name}}',
                      })}
                      title={t('tenant.agentDefinitions.openActions', {
                        name: def.display_name ?? def.name,
                        defaultValue: 'Open actions for {{name}}',
                      })}
                      className="p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                    >
                      <MoreVertical size={14} />
                    </button>
                  </Dropdown>
                </div>
              }
            >
              <div className="space-y-2">
                <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2">
                  {def.system_prompt
                    ? def.system_prompt.substring(0, 120) +
                      (def.system_prompt.length > 120 ? '...' : '')
                    : t('tenant.agentDefinitions.noSystemPrompt', {
                        defaultValue: 'No system prompt',
                      })}
                </p>

                <div className="flex flex-wrap gap-1">
                  <Tag
                    {...(def.project_id ? { color: 'purple' as const } : {})}
                    className="max-w-full truncate text-2xs"
                  >
                    {getScopeLabel(def.project_id)}
                  </Tag>
                  {def.model && <Tag className="text-2xs">{def.model}</Tag>}
                  {def.execution_backend?.type === 'acp_external' && (
                    <Tag color="cyan" className="text-2xs">
                      ACP
                    </Tag>
                  )}
                  {def.can_spawn && (
                    <Tag color="blue" className="text-2xs">
                      {t('tenant.agentDefinitions.capabilities.spawn', { defaultValue: 'Spawn' })}
                    </Tag>
                  )}
                  {def.agent_to_agent_enabled && (
                    <Tag color="green" className="text-2xs">
                      A2A
                    </Tag>
                  )}
                  {def.source === 'filesystem' && (
                    <Tag color="orange" className="text-2xs">
                      FS
                    </Tag>
                  )}
                </div>

                <div className="flex items-center justify-between text-xs-plus text-slate-400 dark:text-slate-500 pt-1 border-t border-slate-100 dark:border-slate-700">
                  <span>
                    {t('tenant.agentDefinitions.metrics.invocations', {
                      count: def.total_invocations,
                      defaultValue: '{{count}} invocations',
                    })}
                  </span>
                  {def.success_rate !== null && (
                    <span>
                      {t('tenant.agentDefinitions.metrics.success', {
                        percent: Math.round(def.success_rate * 100),
                        defaultValue: '{{percent}}% success',
                      })}
                    </span>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {total > pageSize && (
        <div className="flex justify-end">
          <Pagination
            current={page}
            pageSize={pageSize}
            total={total}
            showSizeChanger
            pageSizeOptions={['20', '50', '100']}
            aria-label={t('common.pagination.label', { defaultValue: 'Pagination' })}
            showTotal={(nextTotal) =>
              t('common.pagination.total', {
                total: nextTotal,
                defaultValue: '{{total}} total',
              })
            }
            onChange={(nextPage, nextPageSize) => {
              void loadDefinitionsPage({ page: nextPage, pageSize: nextPageSize });
            }}
          />
        </div>
      )}

      {/* Modal */}
      {canManageAgents ? (
        <AgentDefinitionModal
          isOpen={isModalOpen}
          onClose={handleModalClose}
          onSuccess={handleModalSuccess}
          definition={editingDef}
          projectOptions={projectScopeOptions}
          initialProjectId={createProjectId}
          tenantId={tenantId}
        />
      ) : null}
    </div>
  );
};

export default AgentDefinitions;
