import { scopedPageLocation, splitPageLocation } from '../../../../packages/plugin-slots/src/pageLocation';
import type { SidebarBindings } from '../../../../packages/plugin-slots/src/sidebar';
import type { AgentConversation, WorkspaceSummary } from '../types';

export type ExecutionTargetFilter = 'all' | 'local' | 'cloud';

export type SidebarHostPage = {
  enabled: boolean;
  projectId: string | null;
  pluginId: string;
  commands: readonly string[];
  page: {
    id: string;
    title: string;
    routes: readonly string[];
    targets: readonly string[];
    contributes_to?: string;
    sidebar?: SidebarBindings;
    navigation_actions?: readonly ('primary-create' | 'group-create')[];
  };
};

export type ConversationSource = {
  id: string;
  title: string;
  executionTarget: 'local' | 'cloud';
  workspaceId: string | null;
  workspaceName: string | null;
  updatedAt: string | null;
  createdAt: string | null;
  taskId: string | null;
};

const UNBOUND = '';

function text(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function routeParts(pattern: string): string[] {
  return pattern.split('/').filter(Boolean);
}

/** Structural match for a declared page route, including tenant and project params. */
export function routeMatches(
  pattern: string,
  pathname: string,
  scope: { tenantId: string; projectId: string | null },
): boolean {
  const template = routeParts(pattern);
  const actual = routeParts(pathname);
  if (template.length !== actual.length) return false;
  for (const [index, part] of template.entries()) {
    const value = decodeURIComponent(actual[index] ?? '');
    if (!part.startsWith(':')) {
      if (part !== value) return false;
      continue;
    }
    const name = part.slice(1);
    if (name === 'tenantId' && value !== scope.tenantId) return false;
    if (name === 'projectId' && scope.projectId && value !== scope.projectId) return false;
  }
  return true;
}

export function fillRoute(pattern: string, params: Readonly<Record<string, string>>): string | null {
  const filled = pattern.split('/').map((part) => {
    if (!part.startsWith(':')) return part;
    const value = params[part.slice(1)];
    return value ? encodeURIComponent(value) : null;
  });
  if (filled.some((part) => part === null)) return null;
  const path = filled.join('/');
  return path.startsWith('/') ? path : `/${path}`;
}

export function readRouteParam(pattern: string, address: string, name: string): string | null {
  const { pathname } = splitPageLocation(address);
  const template = routeParts(pattern);
  const actual = routeParts(pathname);
  if (template.length !== actual.length) return null;
  let found: string | null = null;
  for (const [index, part] of template.entries()) {
    const value = decodeURIComponent(actual[index] ?? '');
    if (part.startsWith(':')) {
      if (part.slice(1) === name) found = value;
    } else if (part !== value) return null;
  }
  return found;
}

/**
 * Project pages carry the same scope query as the cloud sidebar.
 * Tenant pages use packageScope instead of a project id.
 */
export function signedDeepLink(
  pathname: string,
  extra: Readonly<Record<string, string>>,
  scope: { tenant: string; project: string | null; plugin: string },
): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(extra)) {
    if (value) query.set(key, value);
  }
  const address = pathname + (query.size ? `?${query.toString()}` : '');
  const location = scopedPageLocation(address, {
    tenant: scope.tenant,
    ...(scope.project
      ? { project: scope.project, projectId: scope.project }
      : { packageScope: 'tenant' }),
    businessPackage: scope.plugin,
  });
  return location.pathname + (location.search ? `?${location.search}` : '');
}

export function findSidebarOwner<T extends SidebarHostPage>(
  entries: readonly T[],
  tenant: string,
  project: string | null,
  slot: 'rows' | 'groups',
  address: string,
): T | null {
  if (!project) return null;
  const { pathname } = splitPageLocation(address);
  const eligible = entries.filter((entry) => {
    const binding = entry.page.sidebar?.[slot];
    return (
      entry.enabled &&
      entry.projectId === project &&
      entry.page.targets.includes('desktop-renderer') &&
      !!binding &&
      entry.commands.includes(binding.command)
    );
  });
  return (
    eligible.find((entry) =>
      entry.page.routes.some((route) =>
        routeMatches(route, pathname, { tenantId: tenant, projectId: project }),
      ),
    ) ??
    eligible[0] ??
    null
  );
}

export function linkForAction(
  entries: readonly SidebarHostPage[],
  links: readonly { id: string; path: string }[],
  tenant: string,
  action: 'primary-create' | 'group-create',
): string | null {
  for (const entry of entries) {
    if (!entry.enabled || !entry.page.navigation_actions?.includes(action)) continue;
    const id = [entry.projectId || tenant, entry.pluginId, entry.page.id].join('/');
    const link = links.find((item) => item.id === id);
    if (link) return link.path;
  }
  return null;
}

export function readConversationSources(rows: readonly Record<string, unknown>[]): ConversationSource[] {
  return rows.flatMap((row) => {
    if (row.hidden === true) return [];
    const id = text(row.id);
    const title = text(row.label);
    if (!id || !title) return [];
    return [
      {
        id,
        title,
        executionTarget: row.target === 'local' ? 'local' : 'cloud',
        workspaceId: text(row.group),
        workspaceName: text(row.groupLabel),
        updatedAt: text(row.updatedAt),
        createdAt: text(row.createdAt),
        taskId: text(row.child),
      },
    ];
  });
}

export function readGroupSources(rows: readonly Record<string, unknown>[]): { id: string; name: string }[] {
  return rows.flatMap((row) => {
    const id = text(row.id);
    const name = text(row.label);
    return id && name ? [{ id, name }] : [];
  });
}

/** A settled node lets an empty workspace read as empty instead of "load on expand". */
export function settledWorkspaceNodes(
  workspaceIds: readonly string[],
  status: { loading: boolean; error: string },
): Record<string, { loading: boolean; error: string | null }> {
  return Object.fromEntries(
    workspaceIds.map((id) => [id, { loading: status.loading, error: status.error || null }]),
  );
}

export function buildSidebarTree(
  conversations: readonly ConversationSource[],
  groups: readonly { id: string; name: string }[],
  filter: ExecutionTargetFilter,
  tenantId: string,
  projectId: string,
): { workspaces: WorkspaceSummary[]; conversationsByWorkspace: Record<string, AgentConversation[]> } {
  const visible = conversations.filter(
    (conversation) => filter === 'all' || conversation.executionTarget === filter,
  );
  const workspaces: WorkspaceSummary[] = groups.map((group) => ({
    id: group.id,
    name: group.name,
    tenant_id: tenantId,
    project_id: projectId,
  }));
  const known = new Set(workspaces.map((workspace) => workspace.id));
  const conversationsByWorkspace: Record<string, AgentConversation[]> = { [UNBOUND]: [] };
  for (const source of visible) {
    const workspaceId = source.workspaceId ?? UNBOUND;
    if (workspaceId && !known.has(workspaceId)) {
      known.add(workspaceId);
      workspaces.push({
        id: workspaceId,
        name: source.workspaceName ?? workspaceId,
        tenant_id: tenantId,
        project_id: projectId,
      });
    }
    const created = source.createdAt ?? source.updatedAt ?? '1970-01-01T00:00:00.000Z';
    const conversation: AgentConversation = {
      id: source.id,
      project_id: projectId,
      tenant_id: tenantId,
      user_id: '',
      title: source.title,
      status: 'ready',
      message_count: 0,
      created_at: created,
      updated_at: source.updatedAt ?? created,
      workspace_id: source.workspaceId,
      workspace_name: source.workspaceName,
      ...(source.taskId ? { linked_workspace_task_id: source.taskId } : {}),
      execution_target: source.executionTarget,
    };
    const bucket = conversationsByWorkspace[workspaceId] ?? [];
    bucket.push(conversation);
    conversationsByWorkspace[workspaceId] = bucket;
  }
  return { workspaces, conversationsByWorkspace };
}

export function workspacePagePath(
  entries: readonly SidebarHostPage[],
  tenant: string,
  project: string,
  workspaceId: string,
): string | null {
  let best: { path: string; score: number } | null = null;
  for (const entry of entries) {
    if (
      !entry.enabled ||
      entry.projectId !== project ||
      entry.page.contributes_to ||
      !entry.page.targets.includes('desktop-renderer')
    )
      continue;
    for (const pattern of entry.page.routes) {
      if (!pattern.endsWith(':workspaceId')) continue;
      const pathname = fillRoute(pattern, { tenantId: tenant, projectId: project, workspaceId });
      if (!pathname || !pathname.includes('/tenant/')) continue;
      const path = signedDeepLink(pathname, {}, { tenant, project, plugin: entry.pluginId });
      const score = pattern.split('/').length;
      if (!best || score < best.score) best = { path, score };
    }
  }
  return best?.path ?? null;
}

export function chatDeepLink(
  owner: SidebarHostPage | null,
  tenant: string,
  project: string,
  conversationId: string | null,
  workspaceId: string | null,
): string | null {
  const binding = owner?.page.sidebar?.rows;
  if (!owner || !binding) return null;
  const pattern = conversationId ? binding.row_route : binding.route;
  if (!pattern) return null;
  const pathname = fillRoute(pattern, {
    tenantId: tenant,
    projectId: project,
    ...(conversationId && binding.row_param ? { [binding.row_param]: conversationId } : {}),
  });
  if (!pathname) return null;
  const extra: Record<string, string> = {};
  if (workspaceId && binding.group_query) extra[binding.group_query] = workspaceId;
  return signedDeepLink(pathname, extra, { tenant, project, plugin: owner.pluginId });
}

export function activeConversationId(owner: SidebarHostPage | null, address: string): string | null {
  const binding = owner?.page.sidebar?.rows;
  if (!binding?.row_route || !binding.row_param) return null;
  return readRouteParam(binding.row_route, address, binding.row_param);
}

export function activeWorkspaceId(
  owner: SidebarHostPage | null,
  entries: readonly SidebarHostPage[],
  address: string,
  conversationWorkspaceId: string | null,
): string {
  const groupQuery = owner?.page.sidebar?.rows?.group_query;
  if (groupQuery) {
    const selected = new URLSearchParams(splitPageLocation(address).search).get(groupQuery);
    if (selected) return selected;
  }
  for (const entry of entries) {
    for (const pattern of entry.page.routes) {
      if (!pattern.endsWith(':workspaceId')) continue;
      const id = readRouteParam(pattern, address, 'workspaceId');
      if (id) return id;
    }
  }
  return conversationWorkspaceId ?? '';
}
