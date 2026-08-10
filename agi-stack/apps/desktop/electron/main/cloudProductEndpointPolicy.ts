export type CloudProductRequestMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export type CloudProductEndpoint = Readonly<{
  kind: 'identity-catalog' | 'tenant-admin' | 'project' | 'workspace';
  tenantId: string | null;
  projectId: string | null;
  workspaceId: string | null;
}>;

type EndpointRequest = Readonly<{
  method?: CloudProductRequestMethod;
  body?: Readonly<Record<string, unknown>>;
  form?: readonly Readonly<Record<string, unknown>>[];
  response?: Readonly<{
    kind: 'binary' | 'event-stream';
    max_bytes: number;
  }>;
}>;

const PROJECT_COLLECTION_QUERY = new Set(['page', 'page_size', 'tenant_id']);
const TENANT_COLLECTION_QUERY = new Set(['page', 'page_size']);
const WORKSPACE_COLLECTION_QUERY = new Set(['limit', 'offset']);
const WORKSPACE_MEMBER_QUERY = new Set(['limit', 'offset']);
const WORKSPACE_AGENT_QUERY = new Set(['active_only', 'limit', 'offset']);
const CRON_COLLECTION_QUERY = new Set(['include_disabled', 'limit', 'offset']);
const CRON_RUNS_QUERY = new Set(['limit', 'offset']);
const CONVERSATION_LIST_QUERY = new Set([
  'project_id',
  'status',
  'limit',
  'offset',
  'workspace_id',
  'unbound_only',
]);
const CONVERSATION_MESSAGES_QUERY = new Set([
  'project_id',
  'limit',
  'from_time_us',
  'from_counter',
  'before_time_us',
  'before_counter',
]);
const TENANT_PROJECT_QUERY = new Set([
  'tenant_id',
  'page',
  'page_size',
  'search',
  'visibility',
  'owner_id',
]);
const TASK_RECENT_QUERY = new Set(['limit', 'offset', 'search', 'status']);
const TENANT_AUDIT_QUERY = new Set([
  'limit',
  'offset',
  'action',
  'resource_type',
  'actor',
  'start_time',
  'end_time',
]);
const TENANT_AUDIT_EXPORT_QUERY = new Set([
  'format',
  'action',
  'resource_type',
  'actor',
  'hook_name',
  'executor_kind',
  'hook_family',
  'isolation_mode',
  'start_time',
  'end_time',
]);
const TENANT_EVENT_QUERY = new Set([
  'tenant_id',
  'page',
  'page_size',
  'event_type',
  'date_from',
  'date_to',
]);
const TENANT_GENE_QUERY = new Set([
  'tenant_id',
  'page',
  'page_size',
  'status',
  'scope',
  'search',
]);

export function authorizeCloudProductEndpoint(
  request: EndpointRequest,
  target: URL,
): CloudProductEndpoint | null {
  const segments = target.pathname.split('/');
  if (segments[1] !== 'api' || segments[2] !== 'v1') return null;

  const privilegedTransfer = authorizePrivilegedTransfer(request, target, segments);
  if (privilegedTransfer) return privilegedTransfer;
  if (request.form !== undefined || request.response !== undefined) return null;

  const desktopCloudClient = authorizeDesktopCloudClientCohort(request, target, segments);
  if (desktopCloudClient) return desktopCloudClient;

  const managedResource = authorizeManagedResource(request, target, segments);
  if (managedResource) return managedResource;

  const tenantProject = authorizeTenantProjectCohort(request, target, segments);
  if (tenantProject) return tenantProject;

  const tenantManagement = authorizeTenantManagementCohort(request, target, segments);
  if (tenantManagement) return tenantManagement;

  const operational = authorizeOperationalCohort(request, target, segments);
  if (operational) return operational;

  const identity = authorizeIdentityCatalog(request, target, segments);
  if (identity) return identity;

  const workspace = authorizeWorkspaceHierarchy(request, target, segments);
  if (workspace) return workspace;

  const workspaceProjection = authorizeWorkspaceProjection(request, target, segments);
  if (workspaceProjection) return workspaceProjection;

  const agent = authorizeAgentCohort(request, target, segments);
  if (agent) return agent;

  return authorizeProjectCohort(request, target, segments);
}

function authorizeDesktopCloudClientCohort(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  const identity = authorizeDesktopIdentityMutation(request, target, segments);
  if (identity) return identity;
  const runtime = authorizeDesktopRuntimeCatalog(request, target, segments);
  if (runtime) return runtime;
  return authorizeDesktopSettingsRoute(request, target, segments);
}

function authorizeDesktopIdentityMutation(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (
    target.pathname === '/api/v1/auth/device/approve' &&
    request.method === 'POST' &&
    noQuery(target)
  ) {
    return endpoint('identity-catalog', null, null, null);
  }
  if (
    segments.length === 6 &&
    segments[3] === 'invitations' &&
    segments[4] === 'accept' &&
    request.method === 'POST' &&
    noQuery(target)
  ) {
    requiredIdentifier(segments[5]);
    return endpoint('identity-catalog', null, null, null);
  }
  if (
    target.pathname === '/api/v1/tenants/' &&
    request.method === 'POST' &&
    noQuery(target)
  ) {
    return endpoint('identity-catalog', null, null, null);
  }
  if (
    target.pathname === '/api/v1/users/me' &&
    request.method === 'PUT' &&
    noQuery(target)
  ) {
    return endpoint('identity-catalog', null, null, null);
  }
  if (
    target.pathname === '/api/v1/auth/force-change-password' &&
    request.method === 'POST' &&
    noQuery(target)
  ) {
    return endpoint('identity-catalog', null, null, null);
  }
  return null;
}

function authorizeDesktopRuntimeCatalog(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (segments[3] === 'instance-templates') {
    const collection = segments.length === 5 && segments[4] === '';
    if (
      collection &&
      request.method === 'GET' &&
      allowedQueryKeys(
        target.searchParams,
        new Set(['page', 'page_size', 'is_published']),
        ['page', 'page_size'],
      )
    ) {
      return endpoint('tenant-admin', null, null, null);
    }
    if (collection && request.method === 'POST' && noQuery(target)) {
      return endpoint(
        'tenant-admin',
        requiredBodyIdentifier(request.body, 'tenant_id'),
        null,
        null,
      );
    }
    requiredIdentifier(segments[4]);
    if (
      segments.length === 5 &&
      methodIn(request, ['GET', 'DELETE']) &&
      noQuery(target)
    ) {
      return endpoint('tenant-admin', null, null, null);
    }
    if (
      segments.length === 6 &&
      ((segments[5] === 'items' && request.method === 'GET') ||
        (['publish', 'clone'].includes(segments[5] ?? '') && request.method === 'POST')) &&
      noQuery(target)
    ) {
      return endpoint('tenant-admin', null, null, null);
    }
    return null;
  }
  if (segments[3] === 'clusters') {
    if (
      segments.length === 5 &&
      segments[4] === '' &&
      request.method === 'GET' &&
      exactQueryKeys(target.searchParams, new Set(['page', 'page_size']))
    ) {
      return endpoint('tenant-admin', null, null, null);
    }
    if (
      segments.length === 6 &&
      segments[5] === 'health' &&
      request.method === 'GET' &&
      noQuery(target)
    ) {
      requiredIdentifier(segments[4]);
      return endpoint('tenant-admin', null, null, null);
    }
    return null;
  }
  if (segments[3] === 'deploys') {
    if (
      segments.length === 5 &&
      segments[4] === '' &&
      request.method === 'GET' &&
      exactQueryKeys(target.searchParams, new Set(['instance_id', 'page', 'page_size']))
    ) {
      return endpoint('tenant-admin', null, null, null);
    }
    if (segments.length === 5 && request.method === 'GET' && noQuery(target)) {
      requiredIdentifier(segments[4]);
      return endpoint('tenant-admin', null, null, null);
    }
    return null;
  }
  if (segments[3] === 'instances') {
    if (
      segments.length === 5 &&
      segments[4] === '' &&
      request.method === 'GET' &&
      allowedQueryKeys(
        target.searchParams,
        new Set(['page', 'page_size', 'search', 'status']),
        ['page', 'page_size'],
      )
    ) {
      return endpoint('tenant-admin', null, null, null);
    }
    requiredIdentifier(segments[4]);
    if (segments.length === 5 && request.method === 'DELETE' && noQuery(target)) {
      return endpoint('tenant-admin', null, null, null);
    }
    if (
      segments.length === 6 &&
      segments[5] === 'restart' &&
      request.method === 'POST' &&
      noQuery(target)
    ) {
      return endpoint('tenant-admin', null, null, null);
    }
    return null;
  }
  if (
    target.pathname === '/api/v1/projects/sandboxes' &&
    request.method === 'GET' &&
    exactQueryKeys(target.searchParams, new Set(['limit', 'offset'])) &&
    target.searchParams.get('limit') === '100' &&
    target.searchParams.get('offset') === '0'
  ) {
    return endpoint('project', null, null, null);
  }
  if (
    segments.length === 7 &&
    segments[3] === 'projects' &&
    segments[5] === 'sandbox' &&
    segments[6] === 'stats' &&
    request.method === 'GET' &&
    noQuery(target)
  ) {
    return endpoint('project', null, requiredIdentifier(segments[4]), null);
  }
  return null;
}

function authorizeDesktopSettingsRoute(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (
    segments[3] === 'skills' &&
    segments[4] === 'evolution' &&
    exactQueryKeys(target.searchParams, new Set(['tenant_id']))
  ) {
    const tenantId = requiredIdentifier(target.searchParams.get('tenant_id'));
    if (
      segments.length === 6 &&
      ((['overview', 'config'].includes(segments[5] ?? '') && request.method === 'GET') ||
        (segments[5] === 'config' && request.method === 'PUT') ||
        (segments[5] === 'run' && request.method === 'POST'))
    ) {
      return endpoint('tenant-admin', tenantId, null, null);
    }
    if (
      segments.length === 8 &&
      segments[5] === 'jobs' &&
      ['apply', 'reject'].includes(segments[7] ?? '') &&
      request.method === 'POST'
    ) {
      requiredIdentifier(segments[6]);
      return endpoint('tenant-admin', tenantId, null, null);
    }
    return null;
  }
  if (segments[3] === 'channels') {
    if (
      segments.length === 8 &&
      segments[4] === 'tenants' &&
      segments[6] === 'plugins' &&
      segments[7] === 'channel-catalog' &&
      request.method === 'GET' &&
      noQuery(target)
    ) {
      return endpoint('tenant-admin', requiredIdentifier(segments[5]), null, null);
    }
    if (
      segments.length === 10 &&
      segments[4] === 'tenants' &&
      segments[6] === 'plugins' &&
      segments[7] === 'channel-catalog' &&
      segments[9] === 'schema' &&
      request.method === 'GET' &&
      noQuery(target)
    ) {
      requiredIdentifier(segments[8]);
      return endpoint('tenant-admin', requiredIdentifier(segments[5]), null, null);
    }
    if (
      segments.length === 7 &&
      segments[4] === 'projects' &&
      segments[6] === 'configs' &&
      methodIn(request, ['GET', 'POST']) &&
      noQuery(target)
    ) {
      return endpoint('project', null, requiredIdentifier(segments[5]), null);
    }
    if (segments[4] === 'configs') {
      requiredIdentifier(segments[5]);
      if (
        segments.length === 6 &&
        methodIn(request, ['PUT', 'DELETE']) &&
        noQuery(target)
      ) {
        return endpoint('project', null, null, null);
      }
      if (
        segments.length === 7 &&
        segments[6] === 'test' &&
        request.method === 'POST' &&
        noQuery(target)
      ) {
        return endpoint('project', null, null, null);
      }
    }
    return null;
  }
  if (
    segments[3] === 'subagents' &&
    segments[4] === 'templates' &&
    exactQueryKeys(target.searchParams, new Set(['tenant_id']))
  ) {
    const tenantId = requiredIdentifier(target.searchParams.get('tenant_id'));
    if (
      segments.length === 6 &&
      ['categories', 'seed'].includes(segments[5] ?? '') &&
      ((segments[5] === 'categories' && request.method === 'GET') ||
        (segments[5] === 'seed' && request.method === 'POST'))
    ) {
      return endpoint('tenant-admin', tenantId, null, null);
    }
    if (segments.length === 6 && request.method === 'GET') {
      requiredIdentifier(segments[5]);
      return endpoint('tenant-admin', tenantId, null, null);
    }
    if (
      segments.length === 7 &&
      segments[6] === 'install' &&
      request.method === 'POST'
    ) {
      requiredIdentifier(segments[5]);
      return endpoint('tenant-admin', tenantId, null, null);
    }
    return null;
  }
  if (
    segments.length === 6 &&
    segments[3] === 'subagents' &&
    segments[4] === 'templates' &&
    segments[5] === 'list' &&
    request.method === 'GET' &&
    allowedQueryKeys(
      target.searchParams,
      new Set(['tenant_id', 'limit', 'offset', 'category', 'query']),
      ['tenant_id', 'limit', 'offset'],
    )
  ) {
    return endpoint(
      'tenant-admin',
      requiredIdentifier(target.searchParams.get('tenant_id')),
      null,
      null,
    );
  }
  return null;
}

function authorizeTenantProjectCohort(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (segments[3] !== 'projects') return null;
  const collection = segments.length === 4 || (segments.length === 5 && segments[4] === '');
  if (collection) {
    if (
      request.method === 'GET' &&
      allowedQueryKeys(target.searchParams, TENANT_PROJECT_QUERY, [
        'tenant_id',
        'page',
        'page_size',
      ])
    ) {
      return endpoint(
        'identity-catalog',
        requiredIdentifier(target.searchParams.get('tenant_id')),
        null,
        null,
      );
    }
    if (request.method === 'POST' && noQuery(target)) {
      return endpoint(
        'identity-catalog',
        requiredBodyIdentifier(request.body, 'tenant_id'),
        null,
        null,
      );
    }
    return null;
  }
  const projectId = requiredIdentifier(segments[4]);
  if (segments.length === 5) {
    if (
      request.method === 'GET' &&
      exactQueryKeys(target.searchParams, new Set(['tenant_id']))
    ) {
      return endpoint(
        'identity-catalog',
        requiredIdentifier(target.searchParams.get('tenant_id')),
        null,
        null,
      );
    }
    if (
      (request.method === 'PUT' || request.method === 'DELETE') &&
      noQuery(target)
    ) {
      return endpoint('project', null, projectId, null);
    }
  }
  if (
    segments.length === 6 &&
    segments[5] === 'members' &&
    request.method === 'GET' &&
    noQuery(target)
  ) {
    return endpoint('project', null, projectId, null);
  }
  return null;
}

function authorizeTenantManagementCohort(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  const tenant = authorizeTenantResource(request, target, segments);
  if (tenant) return tenant;
  const acp = authorizeTenantAcp(request, target, segments);
  if (acp) return acp;
  const events = authorizeTenantEvents(request, target, segments);
  if (events) return events;
  const genes = authorizeTenantGenes(request, target, segments);
  if (genes) return genes;
  const webhooks = authorizeTenantWebhooks(request, target, segments);
  if (webhooks) return webhooks;
  return authorizeTenantPatterns(request, target, segments);
}

function authorizeTenantResource(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (segments[3] !== 'tenants' || segments.length < 5) return null;
  const tenantId = requiredIdentifier(segments[4]);
  const scoped = (): CloudProductEndpoint => endpoint('tenant-admin', tenantId, null, null);
  if (segments.length === 5) {
    return methodIn(request, ['GET', 'PUT', 'DELETE']) && noQuery(target) ? scoped() : null;
  }
  const resource = segments[5];
  if (segments.length === 6) {
    if (
      ['stats', 'billing', 'invoices', 'registries', 'smtp-config', 'gene-policies'].includes(
        resource ?? '',
      ) &&
      ((resource === 'registries' && methodIn(request, ['GET', 'POST'])) ||
        (resource === 'smtp-config' && methodIn(request, ['GET', 'PUT', 'DELETE'])) ||
        (resource !== 'registries' && resource !== 'smtp-config' && request.method === 'GET')) &&
      noQuery(target)
    ) {
      return scoped();
    }
    if (resource === 'upgrade' && request.method === 'POST' && noQuery(target)) return scoped();
    if (resource === 'members' && request.method === 'GET' && noQuery(target)) return scoped();
    if (resource === 'invitations') {
      if (request.method === 'POST' && noQuery(target)) return scoped();
      if (
        request.method === 'GET' &&
        allowedQueryKeys(target.searchParams, new Set(['limit', 'offset']), [])
      ) {
        return scoped();
      }
    }
    if (
      resource === 'analytics' &&
      request.method === 'GET' &&
      exactQueryKeys(target.searchParams, new Set(['period'])) &&
      ['7d', '30d', '90d'].includes(target.searchParams.get('period') ?? '')
    ) {
      return scoped();
    }
    if (
      resource === 'audit-logs' &&
      request.method === 'GET' &&
      allowedQueryKeys(target.searchParams, TENANT_AUDIT_QUERY, ['limit', 'offset'])
    ) {
      return scoped();
    }
    return null;
  }
  if (
    segments.length === 7 &&
    resource === 'members' &&
    methodIn(request, ['PATCH', 'DELETE']) &&
    noQuery(target)
  ) {
    requiredIdentifier(segments[6]);
    return scoped();
  }
  if (segments.length === 7 && resource === 'registries') {
    requiredIdentifier(segments[6]);
    return methodIn(request, ['PUT', 'DELETE']) && noQuery(target) ? scoped() : null;
  }
  if (
    segments.length === 8 &&
    resource === 'registries' &&
    segments[7] === 'test' &&
    request.method === 'POST' &&
    noQuery(target)
  ) {
    requiredIdentifier(segments[6]);
    return scoped();
  }
  if (segments.length === 7 && resource === 'gene-policies') {
    requiredIdentifier(segments[6]);
    return methodIn(request, ['PUT', 'DELETE']) && noQuery(target) ? scoped() : null;
  }
  if (
    segments.length === 7 &&
    resource === 'smtp-config' &&
    segments[6] === 'test' &&
    request.method === 'POST' &&
    noQuery(target)
  ) {
    return scoped();
  }
  if (resource === 'audit-logs') {
    if (
      segments.length === 7 &&
      segments[6] === 'filter' &&
      request.method === 'GET' &&
      allowedQueryKeys(target.searchParams, TENANT_AUDIT_QUERY, ['limit', 'offset'])
    ) {
      return scoped();
    }
    if (
      segments.length === 8 &&
      segments[6] === 'runtime-hooks' &&
      segments[7] === 'summary' &&
      request.method === 'GET' &&
      noQuery(target)
    ) {
      return scoped();
    }
  }
  if (resource !== 'trust') return null;
  if (segments.length === 7 && segments[6] === 'policies') {
    if (request.method === 'POST' && noQuery(target)) return scoped();
    if (
      request.method === 'GET' &&
      exactQueryKeys(target.searchParams, new Set(['workspace_id']))
    ) {
      return scoped();
    }
  }
  if (
    segments.length === 8 &&
    segments[6] === 'policies' &&
    request.method === 'DELETE' &&
    exactQueryKeys(target.searchParams, new Set(['workspace_id']))
  ) {
    requiredIdentifier(segments[7]);
    return scoped();
  }
  if (
    segments.length === 7 &&
    segments[6] === 'decision-records' &&
    request.method === 'GET' &&
    allowedQueryKeys(
      target.searchParams,
      new Set(['workspace_id', 'agent_id', 'decision_type']),
      ['workspace_id'],
    )
  ) {
    return scoped();
  }
  if (
    segments.length === 9 &&
    segments[6] === 'approval-requests' &&
    segments[8] === 'resolve' &&
    request.method === 'POST' &&
    noQuery(target)
  ) {
    requiredIdentifier(segments[7]);
    return scoped();
  }
  return null;
}

function authorizeTenantAcp(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (segments[3] !== 'acp' || segments[4] !== 'tenants' || segments.length < 7) return null;
  const tenantId = requiredIdentifier(segments[5]);
  const resource = segments[6];
  if (
    segments.length === 7 &&
    ((['status', 'runner-pools'].includes(resource ?? '') && request.method === 'GET') ||
      (resource === 'external-agents' && request.method === 'POST')) &&
    noQuery(target)
  ) {
    return endpoint('tenant-admin', tenantId, null, null);
  }
  if (segments.length >= 8 && resource === 'external-agents') {
    requiredIdentifier(segments[7]);
    const allowed =
      (segments.length === 8 && methodIn(request, ['PUT', 'DELETE'])) ||
      (segments.length === 9 && segments[8] === 'test' && request.method === 'POST');
    return allowed && noQuery(target) ? endpoint('tenant-admin', tenantId, null, null) : null;
  }
  return null;
}

function authorizeTenantEvents(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (segments[3] !== 'events' || request.method !== 'GET') return null;
  if (
    segments.length === 4 &&
    allowedQueryKeys(target.searchParams, TENANT_EVENT_QUERY, ['tenant_id', 'page', 'page_size'])
  ) {
    return endpoint(
      'tenant-admin',
      requiredIdentifier(target.searchParams.get('tenant_id')),
      null,
      null,
    );
  }
  if (
    segments.length === 5 &&
    segments[4] === 'types' &&
    exactQueryKeys(target.searchParams, new Set(['tenant_id']))
  ) {
    return endpoint(
      'tenant-admin',
      requiredIdentifier(target.searchParams.get('tenant_id')),
      null,
      null,
    );
  }
  return null;
}

function authorizeTenantWebhooks(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (segments[3] !== 'tenant-webhooks' || segments.length !== 5 || !noQuery(target)) return null;
  const identifier = requiredIdentifier(segments[4]);
  if (methodIn(request, ['GET', 'POST'])) {
    return endpoint('tenant-admin', identifier, null, null);
  }
  return methodIn(request, ['PUT', 'DELETE'])
    ? endpoint('tenant-admin', null, null, null)
    : null;
}

function authorizeTenantPatterns(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (
    segments[3] !== 'agent' ||
    segments[4] !== 'workflows' ||
    segments[5] !== 'patterns'
  ) {
    return null;
  }
  if (
    segments.length === 6 &&
    request.method === 'GET' &&
    allowedQueryKeys(target.searchParams, new Set(['tenant_id', 'page', 'page_size']), [
      'tenant_id',
      'page',
      'page_size',
    ])
  ) {
    return endpoint(
      'tenant-admin',
      requiredIdentifier(target.searchParams.get('tenant_id')),
      null,
      null,
    );
  }
  if (
    segments.length === 7 &&
    request.method === 'DELETE' &&
    exactQueryKeys(target.searchParams, new Set(['tenant_id']))
  ) {
    requiredIdentifier(segments[6]);
    return endpoint(
      'tenant-admin',
      requiredIdentifier(target.searchParams.get('tenant_id')),
      null,
      null,
    );
  }
  return null;
}

function authorizeTenantGenes(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (segments[3] !== 'genes' || segments.length < 4) return null;
  const tenantId = target.searchParams.get('tenant_id');
  if (
    !allowedQueryKeys(target.searchParams, new Set([...TENANT_GENE_QUERY, 'page_size']), ['tenant_id'])
  ) {
    return null;
  }
  const scoped = (): CloudProductEndpoint =>
    endpoint('tenant-admin', requiredIdentifier(tenantId), null, null);
  const collection = segments.length === 4 || (segments.length === 5 && segments[4] === '');
  if (collection && methodIn(request, ['GET', 'POST'])) return scoped();
  if (segments.length === 5 && ['genomes', 'evolution'].includes(segments[4] ?? '')) {
    return request.method === 'GET' ? scoped() : null;
  }
  if (segments[4] === 'instances' && segments.length === 7 && segments[6] === 'install') {
    requiredIdentifier(segments[5]);
    return request.method === 'POST' ? scoped() : null;
  }
  requiredIdentifier(segments[4]);
  if (segments.length === 5 && methodIn(request, ['PUT', 'DELETE'])) return scoped();
  if (
    segments.length === 6 &&
    ['publish', 'unpublish', 'ratings'].includes(segments[5] ?? '') &&
    request.method === 'POST'
  ) {
    return scoped();
  }
  if (segments.length === 6 && segments[5] === 'reviews') {
    return methodIn(request, ['GET', 'POST']) ? scoped() : null;
  }
  if (
    segments.length === 7 &&
    segments[5] === 'reviews' &&
    request.method === 'DELETE'
  ) {
    requiredIdentifier(segments[6]);
    return scoped();
  }
  return null;
}

function authorizeOperationalCohort(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  const tasks = authorizeTaskEndpoint(request, target, segments);
  if (tasks) return tasks;
  const agent = authorizeTenantAgentEndpoint(request, target, segments);
  if (agent) return agent;
  const admin = authorizeAdminEndpoint(request, target, segments);
  if (admin) return admin;
  if (
    target.pathname === '/api/v1/search-enhanced/capabilities' &&
    request.method === 'GET' &&
    noQuery(target)
  ) {
    return endpoint('project', null, null, null);
  }
  if (
    target.pathname === '/api/v1/system/info' &&
    request.method === 'GET' &&
    noQuery(target)
  ) {
    return endpoint('tenant-admin', null, null, null);
  }
  return null;
}

function authorizeTaskEndpoint(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (segments[3] !== 'tasks') return null;
  if (
    segments.length === 5 &&
    ['stats', 'queue-depth'].includes(segments[4] ?? '') &&
    request.method === 'GET' &&
    noQuery(target)
  ) {
    return endpoint('project', null, null, null);
  }
  if (
    segments.length === 5 &&
    segments[4] === 'recent' &&
    request.method === 'GET' &&
    allowedQueryKeys(target.searchParams, TASK_RECENT_QUERY, ['limit', 'offset'])
  ) {
    return endpoint('project', null, null, null);
  }
  if (
    segments.length === 5 &&
    segments[4] === 'retry-pending' &&
    request.method === 'POST' &&
    exactQueryKeys(target.searchParams, new Set(['limit']))
  ) {
    return endpoint('tenant-admin', null, null, null);
  }
  if (
    segments.length === 6 &&
    ['retry', 'stop'].includes(segments[5] ?? '') &&
    request.method === 'POST' &&
    noQuery(target)
  ) {
    requiredIdentifier(segments[4]);
    return endpoint('project', null, null, null);
  }
  return null;
}

function authorizeTenantAgentEndpoint(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (segments[3] !== 'agent') return null;
  if (segments[4] === 'bindings') {
    if (
      !allowedQueryKeys(target.searchParams, new Set(['tenant_id', 'agent_id', 'enabled_only']), [
        'tenant_id',
      ])
    ) {
      return null;
    }
    const tenantId = requiredIdentifier(target.searchParams.get('tenant_id'));
    if (segments.length === 5 && methodIn(request, ['GET', 'POST'])) {
      return endpoint('tenant-admin', tenantId, null, null);
    }
    if (segments.length === 6 && segments[5] === 'test' && request.method === 'POST') {
      return endpoint('tenant-admin', tenantId, null, null);
    }
    if (segments.length >= 6) {
      requiredIdentifier(segments[5]);
      const allowed =
        (segments.length === 6 && request.method === 'DELETE') ||
        (segments.length === 7 && segments[6] === 'enabled' && request.method === 'PATCH');
      return allowed ? endpoint('tenant-admin', tenantId, null, null) : null;
    }
  }
  if (segments[4] === 'config') {
    if (
      !allowedQueryKeys(target.searchParams, new Set(['tenant_id', 'expected_revision']), [
        'tenant_id',
      ])
    ) {
      return null;
    }
    const tenantId = requiredIdentifier(target.searchParams.get('tenant_id'));
    if (segments.length === 5 && methodIn(request, ['GET', 'PUT'])) {
      return endpoint('tenant-admin', tenantId, null, null);
    }
    if (
      segments.length === 6 &&
      segments[5] === 'can-modify' &&
      request.method === 'GET'
    ) {
      return endpoint('tenant-admin', tenantId, null, null);
    }
    if (
      segments.length === 7 &&
      segments[5] === 'hooks' &&
      segments[6] === 'catalog' &&
      request.method === 'GET'
    ) {
      return endpoint('tenant-admin', tenantId, null, null);
    }
  }
  if (segments[4] === 'trace' && segments[5] === 'runs') {
    if (
      segments.length === 8 &&
      segments[6] === 'tenant' &&
      request.method === 'GET' &&
      exactQueryKeys(target.searchParams, new Set(['limit']))
    ) {
      return endpoint('tenant-admin', requiredIdentifier(segments[7]), null, null);
    }
    if (
      segments.length === 10 &&
      segments[6] === 'tenant' &&
      segments[8] === 'active' &&
      segments[9] === 'count' &&
      request.method === 'GET' &&
      noQuery(target)
    ) {
      return endpoint('tenant-admin', requiredIdentifier(segments[7]), null, null);
    }
    if (
      segments.length === 9 &&
      segments[7] === 'trace' &&
      request.method === 'GET' &&
      noQuery(target)
    ) {
      requiredIdentifier(segments[6]);
      requiredIdentifier(segments[8]);
      return endpoint('tenant-admin', null, null, null);
    }
  }
  return null;
}

function authorizeAdminEndpoint(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (segments[3] !== 'admin') return null;
  if (segments[4] === 'pool') {
    if (
      !allowedQueryKeys(
        target.searchParams,
        new Set(['scope', 'tenant_id', 'tier', 'status', 'page', 'page_size', 'graceful']),
        ['scope', 'tenant_id'],
      ) ||
      target.searchParams.get('scope') !== 'tenant'
    ) {
      return null;
    }
    const tenantId = requiredIdentifier(target.searchParams.get('tenant_id'));
    const resource = segments[5];
    const allowed =
      (segments.length === 6 &&
        ['status', 'instances', 'metrics'].includes(resource ?? '') &&
        request.method === 'GET') ||
      (segments.length === 7 &&
        resource === 'instances' &&
        request.method === 'DELETE') ||
      (segments.length === 8 &&
        resource === 'instances' &&
        ['pause', 'resume'].includes(segments[7] ?? '') &&
        request.method === 'POST');
    if (segments.length >= 7) requiredIdentifier(segments[6]);
    return allowed ? endpoint('tenant-admin', tenantId, null, null) : null;
  }
  if (segments[4] !== 'dlq') return null;
  if (segments[5] === 'stats') {
    return segments.length === 6 && request.method === 'GET' && noQuery(target)
      ? endpoint('tenant-admin', null, null, null)
      : null;
  }
  if (segments[5] === 'cleanup') {
    return segments.length === 7 &&
      ['expired', 'resolved'].includes(segments[6] ?? '') &&
      request.method === 'POST' &&
      exactQueryKeys(target.searchParams, new Set(['older_than_hours']))
      ? endpoint('tenant-admin', null, null, null)
      : null;
  }
  if (segments[5] !== 'messages') return null;
  if (segments.length === 6 && request.method === 'GET') {
    return allowedQueryKeys(
      target.searchParams,
      new Set(['limit', 'offset', 'status', 'event_type', 'error_type', 'routing_key']),
      ['limit', 'offset'],
    )
      ? endpoint('tenant-admin', null, null, null)
      : null;
  }
  if (
    segments.length === 7 &&
    ['retry', 'discard'].includes(segments[6] ?? '') &&
    request.method === 'POST' &&
    noQuery(target)
  ) {
    return endpoint('tenant-admin', null, null, null);
  }
  if (segments.length >= 7) {
    requiredIdentifier(segments[6]);
    if (segments.length === 7 && request.method === 'GET' && noQuery(target)) {
      return endpoint('tenant-admin', null, null, null);
    }
    if (
      segments.length === 7 &&
      request.method === 'DELETE' &&
      exactQueryKeys(target.searchParams, new Set(['reason']))
    ) {
      return endpoint('tenant-admin', null, null, null);
    }
    if (
      segments.length === 8 &&
      segments[7] === 'retry' &&
      request.method === 'POST' &&
      noQuery(target)
    ) {
      return endpoint('tenant-admin', null, null, null);
    }
  }
  return null;
}

function methodIn(request: EndpointRequest, allowed: readonly CloudProductRequestMethod[]): boolean {
  return request.method !== undefined && allowed.includes(request.method);
}

function authorizeManagedResource(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (
    segments.length === 6 &&
    segments[3] === 'artifacts' &&
    segments[5] === 'content' &&
    (request.method === 'GET' || request.method === 'PUT') &&
    noQuery(target)
  ) {
    requiredIdentifier(segments[4]);
    return endpoint('project', null, null, null);
  }
  if (segments[3] === 'skills') {
    return authorizeManagedSkill(request, target, segments);
  }
  if (segments[3] === 'subagents') {
    return authorizeManagedSubagent(request, target, segments);
  }
  if (segments[3] === 'acp') {
    if (
      segments.length === 7 &&
      segments[4] === 'tenants' &&
      segments[6] === 'external-agents' &&
      request.method === 'GET' &&
      noQuery(target)
    ) {
      return endpoint('project', requiredIdentifier(segments[5]), null, null);
    }
    return null;
  }
  if (segments[3] === 'agent' && segments[4] === 'definitions') {
    return authorizeManagedAgentDefinition(request, target, segments);
  }
  if (segments[3] === 'agent' && segments[4] === 'templates') {
    return authorizeManagedAgentTemplate(request, target, segments);
  }
  return null;
}

function authorizeManagedSkill(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  const tenantId = target.searchParams.get('tenant_id');
  const projectId = target.searchParams.get('project_id');
  const scoped = (): CloudProductEndpoint =>
    endpoint(
      'project',
      tenantId === null ? null : requiredIdentifier(tenantId),
      projectId === null ? null : requiredIdentifier(projectId),
      null,
    );
  if (segments.length === 5 && segments[4] === '') {
    const allowed = new Set(['limit', 'tenant_id', 'project_id']);
    if (
      (request.method !== 'GET' && request.method !== 'POST') ||
      !allowedQueryKeys(
        target.searchParams,
        allowed,
        request.method === 'POST' ? ['tenant_id'] : [],
      )
    ) {
      return null;
    }
    return scoped();
  }
  if (
    segments.length === 5 &&
    segments[4] === 'import' &&
    request.method === 'POST' &&
    allowedQueryKeys(target.searchParams, new Set(['tenant_id', 'project_id']), ['tenant_id'])
  ) {
    return scoped();
  }
  if (
    segments.length === 8 &&
    segments[4] === 'evolution' &&
    segments[5] === 'jobs' &&
    (segments[7] === 'apply' || segments[7] === 'reject') &&
    request.method === 'POST' &&
    allowedQueryKeys(target.searchParams, new Set(['tenant_id']), ['tenant_id'])
  ) {
    requiredIdentifier(segments[6]);
    return scoped();
  }
  if (segments.length < 5) return null;
  requiredIdentifier(segments[4]);
  if (segments.length === 5) {
    return (request.method === 'PUT' || request.method === 'DELETE') &&
      allowedQueryKeys(target.searchParams, new Set(['tenant_id']), ['tenant_id'])
      ? scoped()
      : null;
  }
  const resource = segments[5];
  const tenantQuery = allowedQueryKeys(
    target.searchParams,
    new Set(['tenant_id']),
    ['tenant_id'],
  );
  if (segments.length === 6) {
    if (
      resource === 'status' &&
      request.method === 'PATCH' &&
      allowedQueryKeys(target.searchParams, new Set(['status', 'tenant_id']), ['status'])
    ) {
      return scoped();
    }
    if (resource === 'versions' && request.method === 'GET') {
      return allowedQueryKeys(
        target.searchParams,
        new Set(['tenant_id', 'limit']),
        ['tenant_id', 'limit'],
      )
        ? scoped()
        : null;
    }
    const allowed =
      (resource === 'content' && (request.method === 'GET' || request.method === 'PUT')) ||
      (resource === 'rollback' && request.method === 'POST') ||
      ((resource === 'export' || resource === 'evolution') && request.method === 'GET');
    return allowed && tenantQuery ? scoped() : null;
  }
  if (
    segments.length === 7 &&
    resource === 'versions' &&
    request.method === 'GET' &&
    tenantQuery
  ) {
    requiredIdentifier(segments[6]);
    return scoped();
  }
  if (
    segments.length === 7 &&
    resource === 'evolution' &&
    segments[6] === 'run' &&
    request.method === 'POST' &&
    tenantQuery
  ) {
    return scoped();
  }
  return null;
}

function authorizeManagedAgentDefinition(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (segments.length === 5) {
    const allowed = new Set(['limit', 'enabled_only', 'project_id', 'tenant_id']);
    if (
      !['GET', 'POST'].includes(request.method ?? '') ||
      !allowedQueryKeys(target.searchParams, allowed, [])
    ) {
      return null;
    }
  } else if (segments.length === 6) {
    requiredIdentifier(segments[5]);
    if (!['PUT', 'DELETE'].includes(request.method ?? '')) return null;
    if (!allowedQueryKeys(target.searchParams, new Set(['tenant_id']), [])) return null;
  } else if (segments.length === 7 && segments[6] === 'enabled') {
    requiredIdentifier(segments[5]);
    if (
      request.method !== 'PATCH' ||
      !allowedQueryKeys(target.searchParams, new Set(['tenant_id', 'project_id']), [])
    ) {
      return null;
    }
  } else {
    return null;
  }
  return endpoint(
    'project',
    optionalIdentifier(target.searchParams.get('tenant_id')),
    optionalIdentifier(target.searchParams.get('project_id')),
    null,
  );
}

function authorizeManagedAgentTemplate(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (
    segments.length === 5 &&
    (request.method === 'GET' || request.method === 'POST') &&
    allowedQueryKeys(
      target.searchParams,
      new Set(['tenant_id', 'limit', 'offset']),
      ['tenant_id'],
    )
  ) {
    return endpoint(
      'project',
      requiredIdentifier(target.searchParams.get('tenant_id')),
      null,
      null,
    );
  }
  if (
    segments.length === 6 &&
    request.method === 'DELETE' &&
    noQuery(target)
  ) {
    requiredIdentifier(segments[5]);
    return endpoint('project', null, null, null);
  }
  return null;
}

function authorizeManagedSubagent(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  const tenantId = optionalIdentifier(target.searchParams.get('tenant_id'));
  const projectId = optionalIdentifier(target.searchParams.get('project_id'));
  const scoped = (): CloudProductEndpoint => endpoint('project', tenantId, projectId, null);
  if (segments.length === 5 && segments[4] === '') {
    return (request.method === 'GET' || request.method === 'POST') &&
      allowedQueryKeys(
        target.searchParams,
        new Set(['tenant_id', 'limit', 'include_filesystem']),
        [],
      )
      ? scoped()
      : null;
  }
  if (segments.length === 5) {
    requiredIdentifier(segments[4]);
    return (request.method === 'PUT' || request.method === 'DELETE') &&
      allowedQueryKeys(target.searchParams, new Set(['tenant_id']), [])
      ? scoped()
      : null;
  }
  if (
    segments.length === 6 &&
    segments[4] === 'templates' &&
    segments[5] === 'list' &&
    request.method === 'GET' &&
    allowedQueryKeys(target.searchParams, new Set(['tenant_id', 'limit']), ['limit'])
  ) {
    return scoped();
  }
  if (segments.length === 6 && segments[5] === 'enable' && request.method === 'PATCH') {
    requiredIdentifier(segments[4]);
    return allowedQueryKeys(target.searchParams, new Set(['tenant_id', 'enabled']), ['enabled'])
      ? scoped()
      : null;
  }
  if (
    segments.length === 7 &&
    segments[4] === 'templates' &&
    segments[6] === 'install' &&
    request.method === 'POST' &&
    allowedQueryKeys(target.searchParams, new Set(['tenant_id']), [])
  ) {
    requiredIdentifier(segments[5]);
    return scoped();
  }
  if (
    segments.length === 7 &&
    segments[4] === 'filesystem' &&
    segments[6] === 'import' &&
    request.method === 'POST' &&
    allowedQueryKeys(target.searchParams, new Set(['tenant_id', 'project_id']), [])
  ) {
    requiredIdentifier(segments[5]);
    return scoped();
  }
  return null;
}

function authorizePrivilegedTransfer(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (request.form !== undefined) {
    if (request.method !== 'POST' || request.body !== undefined || request.response !== undefined) {
      return null;
    }
    if (
      segments[3] === 'tenants' &&
      segments[5] === 'projects' &&
      segments[7] === 'workspaces'
    ) {
      const collaborationUpload =
        segments.length === 13 &&
        segments[9] === 'collaboration' &&
        segments[10] === 'mutations' &&
        segments[11] === 'files' &&
        segments[12] === 'upload';
      const blackboardUpload =
        segments.length === 12 &&
        segments[9] === 'blackboard' &&
        segments[10] === 'files' &&
        segments[11] === 'upload';
      if ((collaborationUpload || blackboardUpload) && noQuery(target)) {
        return endpoint(
          'workspace',
          requiredIdentifier(segments[4]),
          requiredIdentifier(segments[6]),
          requiredIdentifier(segments[8]),
        );
      }
    }
    if (
      segments.length === 6 &&
      segments[3] === 'skills' &&
      segments[4] === 'import' &&
      segments[5] === 'zip' &&
      exactQueryKeys(target.searchParams, new Set(['tenant_id']))
    ) {
      const scope = formTextValue(request.form, 'scope');
      const projectId = formTextValue(request.form, 'project_id');
      if (scope !== 'tenant' && scope !== 'project') return null;
      if ((scope === 'project') !== (projectId !== null)) return null;
      return endpoint(
        'project',
        requiredIdentifier(target.searchParams.get('tenant_id')),
        projectId === null ? null : requiredIdentifier(projectId),
        null,
      );
    }
    return null;
  }

  if (request.response?.kind === 'event-stream') {
    if (
      request.body === undefined &&
      segments.length === 6 &&
      segments[3] === 'deploys' &&
      segments[5] === 'progress' &&
      request.method === 'GET' &&
      noQuery(target)
    ) {
      requiredIdentifier(segments[4]);
      return endpoint('project', null, null, null);
    }
    return null;
  }
  if (request.response?.kind !== 'binary' || request.body !== undefined) return null;
  if (
    segments.length === 7 &&
    segments[3] === 'artifacts' &&
    segments[5] === 'content' &&
    segments[6] === 'bytes' &&
    request.method === 'GET' &&
    noQuery(target)
  ) {
    requiredIdentifier(segments[4]);
    return endpoint('project', null, null, null);
  }
  if (
    segments.length === 8 &&
    segments[3] === 'projects' &&
    segments[5] === 'sandbox' &&
    segments[6] === 'files' &&
    segments[7] === 'download' &&
    request.method === 'GET' &&
    exactQueryKeys(target.searchParams, new Set(['path', 'max_bytes'])) &&
    target.searchParams.get('max_bytes') === String(request.response.max_bytes)
  ) {
    return endpoint('project', null, requiredIdentifier(segments[4]), null);
  }
  if (
    segments.length === 7 &&
    segments[3] === 'tenants' &&
    segments[5] === 'audit-logs' &&
    segments[6] === 'export' &&
    request.method === 'GET' &&
    allowedQueryKeys(target.searchParams, TENANT_AUDIT_EXPORT_QUERY, ['format']) &&
    ['csv', 'json'].includes(target.searchParams.get('format') ?? '')
  ) {
    return endpoint('tenant-admin', requiredIdentifier(segments[4]), null, null);
  }
  return null;
}

function formTextValue(
  form: readonly Readonly<Record<string, unknown>>[],
  name: string,
): string | null {
  const matches = form.filter((part) => part.kind === 'text' && part.name === name);
  if (matches.length === 0) return null;
  if (matches.length !== 1 || typeof matches[0]?.value !== 'string') {
    throw new Error('cloud request endpoint is not allowed');
  }
  return matches[0].value as string;
}

function authorizeWorkspaceProjection(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (
    segments.length !== 6 ||
    segments[3] !== 'workspaces' ||
    !['tasks', 'plan'].includes(segments[5] ?? '') ||
    request.method !== 'GET' ||
    !noQuery(target)
  ) {
    return null;
  }
  return endpoint('workspace', null, null, requiredIdentifier(segments[4]));
}

function authorizeAgentCohort(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (segments[3] !== 'agent') return null;
  if (segments[4] === 'conversations') {
    return authorizeConversationEndpoint(request, target, segments);
  }
  if (segments[4] === 'plan') {
    if (
      segments.length === 6 &&
      segments[5] === 'mode' &&
      request.method === 'POST' &&
      noQuery(target)
    ) {
      return endpoint('project', null, null, null);
    }
    if (
      segments.length === 7 &&
      (segments[5] === 'mode' || segments[5] === 'tasks') &&
      request.method === 'GET' &&
      noQuery(target)
    ) {
      requiredIdentifier(segments[6]);
      return endpoint('project', null, null, null);
    }
    return null;
  }
  if (
    segments.length === 6 &&
    segments[4] === 'plans' &&
    segments[5] === 'approve-and-start' &&
    request.method === 'POST' &&
    noQuery(target)
  ) {
    return endpoint('project', null, requiredBodyIdentifier(request.body, 'project_id'), null);
  }
  if (
    segments.length === 6 &&
    segments[4] === 'hitl' &&
    segments[5] === 'respond' &&
    request.method === 'POST' &&
    noQuery(target)
  ) {
    return endpoint('project', null, null, null);
  }
  return authorizeAgentResourceAction(request, target, segments);
}

function authorizeConversationEndpoint(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (segments.length === 5) {
    if (request.method === 'POST' && noQuery(target)) {
      return endpoint('project', null, requiredBodyIdentifier(request.body, 'project_id'), null);
    }
    if (
      request.method === 'GET' &&
      allowedQueryKeys(target.searchParams, CONVERSATION_LIST_QUERY, [
        'project_id',
        'status',
        'limit',
        'offset',
      ])
    ) {
      return endpoint(
        'project',
        null,
        requiredIdentifier(target.searchParams.get('project_id')),
        optionalIdentifier(target.searchParams.get('workspace_id')),
      );
    }
    return null;
  }
  const conversationId = requiredIdentifier(segments[5]);
  void conversationId;
  if (segments.length === 6) {
    return request.method === 'DELETE' &&
      allowedQueryKeys(target.searchParams, new Set(['project_id']), ['project_id'])
      ? endpoint(
          'project',
          null,
          requiredIdentifier(target.searchParams.get('project_id')),
          null,
        )
      : null;
  }
  if (segments.length !== 7) return null;
  const action = segments[6];
  if (action === 'session' && request.method === 'GET') {
    if (
      !allowedQueryKeys(
        target.searchParams,
        new Set(['tenant_id', 'project_id', 'workspace_id']),
        ['tenant_id', 'project_id'],
      )
    ) {
      return null;
    }
    return endpoint(
      'workspace',
      requiredIdentifier(target.searchParams.get('tenant_id')),
      requiredIdentifier(target.searchParams.get('project_id')),
      optionalIdentifier(target.searchParams.get('workspace_id')),
    );
  }
  if (
    ['mode', 'config', 'title', 'summary'].includes(action ?? '') &&
    ((action === 'summary' && request.method === 'POST') ||
      (action !== 'summary' && request.method === 'PATCH')) &&
    allowedQueryKeys(target.searchParams, new Set(['project_id']), ['project_id'])
  ) {
    return endpoint(
      'project',
      null,
      requiredIdentifier(target.searchParams.get('project_id')),
      null,
    );
  }
  if (action === 'messages') {
    if (
      request.method === 'GET' &&
      allowedQueryKeys(target.searchParams, CONVERSATION_MESSAGES_QUERY, ['project_id', 'limit'])
    ) {
      return endpoint(
        'project',
        null,
        requiredIdentifier(target.searchParams.get('project_id')),
        null,
      );
    }
    if (request.method === 'POST' && noQuery(target)) {
      return endpoint('project', null, requiredBodyIdentifier(request.body, 'project_id'), null);
    }
  }
  return null;
}

function authorizeAgentResourceAction(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (!noQuery(target)) {
    if (
      segments.length === 7 &&
      segments[4] === 'runs' &&
      segments[6] === 'changes' &&
      request.method === 'GET' &&
      allowedQueryKeys(target.searchParams, new Set(['expected_revision']), ['expected_revision'])
    ) {
      requiredIdentifier(segments[5]);
      return endpoint('project', null, null, null);
    }
    return null;
  }
  if (segments[4] === 'runs' && segments.length >= 6 && segments.length <= 7) {
    requiredIdentifier(segments[5]);
    if (segments.length === 6 && request.method === 'GET') return endpoint('project', null, null, null);
    const action = segments[6];
    const allowed =
      (action === 'inputs' && (request.method === 'GET' || request.method === 'POST')) ||
      (['pause', 'resume', 'cancel', 'fork', 'review'].includes(action ?? '') &&
        request.method === 'POST');
    return allowed ? endpoint('project', null, null, null) : null;
  }
  if (
    segments.length === 7 &&
    segments[4] === 'run-inputs' &&
    segments[6] === 'promote-to-plan' &&
    request.method === 'POST'
  ) {
    requiredIdentifier(segments[5]);
    return endpoint('project', null, null, null);
  }
  if (
    segments.length === 7 &&
    segments[4] === 'artifact-versions' &&
    ['review', 'deliver'].includes(segments[6] ?? '') &&
    request.method === 'POST'
  ) {
    requiredIdentifier(segments[5]);
    return endpoint('project', null, null, null);
  }
  return null;
}

function authorizeIdentityCatalog(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (request.method !== 'GET' || segments.length !== 4) return null;
  if (
    segments[3] === 'tenants' &&
    exactCatalogQuery(target.searchParams, TENANT_COLLECTION_QUERY, false)
  ) {
    return endpoint('identity-catalog', null, null, null);
  }
  if (
    segments[3] === 'projects' &&
    exactCatalogQuery(target.searchParams, PROJECT_COLLECTION_QUERY, true)
  ) {
    return endpoint(
      'identity-catalog',
      requiredIdentifier(target.searchParams.get('tenant_id')),
      null,
      null,
    );
  }
  return null;
}

function authorizeWorkspaceHierarchy(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (
    segments[3] !== 'tenants' ||
    segments[5] !== 'projects' ||
    (segments[7] !== 'workspaces' && segments[7] !== 'task-sessions')
  ) {
    return null;
  }
  const tenantId = requiredIdentifier(segments[4]);
  const projectId = requiredIdentifier(segments[6]);
  if (segments[7] === 'task-sessions') {
    const allowed =
      (segments.length === 8 && request.method === 'POST') ||
      (segments.length === 9 && segments[8] === 'capabilities' && request.method === 'GET');
    return allowed && noQuery(target)
      ? endpoint('project', tenantId, projectId, null)
      : null;
  }

  if (segments.length === 8) {
    const allowed = request.method === 'GET' || request.method === 'POST';
    if (!allowed) return null;
    if (request.method === 'GET' && !exactQueryKeys(target.searchParams, WORKSPACE_COLLECTION_QUERY)) {
      return null;
    }
    if (request.method === 'POST' && !noQuery(target)) return null;
    return endpoint('project', tenantId, projectId, null);
  }

  const workspaceId = requiredIdentifier(segments[8]);
  if (segments.length === 9) {
    return (request.method === 'GET' || request.method === 'PATCH') && noQuery(target)
      ? endpoint('workspace', tenantId, projectId, workspaceId)
      : null;
  }
  const resource = segments[9];
  if (segments.length === 10) {
    const allowed =
      ((resource === 'members' || resource === 'agents' || resource === 'messages') &&
        (request.method === 'GET' || request.method === 'POST')) ||
      (resource === 'agent-policy' && (request.method === 'GET' || request.method === 'PATCH')) ||
      (resource === 'tool-grants' && request.method === 'GET');
    if (!allowed) return null;
    if (request.method !== 'GET' && !noQuery(target)) return null;
    if (resource === 'members' && request.method === 'GET') {
      if (!exactQueryKeys(target.searchParams, WORKSPACE_MEMBER_QUERY)) return null;
    } else if (resource === 'agents' && request.method === 'GET') {
      if (!exactQueryKeys(target.searchParams, WORKSPACE_AGENT_QUERY)) return null;
    } else if (request.method === 'GET' && !noQuery(target)) {
      return null;
    }
    return endpoint('workspace', tenantId, projectId, workspaceId);
  }
  if (segments.length === 11) {
    if (
      resource === 'collaboration' &&
      ['capabilities', 'authority'].includes(segments[10] ?? '') &&
      request.method === 'GET' &&
      noQuery(target)
    ) {
      return endpoint('workspace', tenantId, projectId, workspaceId);
    }
    requiredIdentifier(segments[10]);
    const allowed =
      (resource === 'members' && (request.method === 'PATCH' || request.method === 'DELETE')) ||
      (resource === 'agents' && request.method === 'DELETE') ||
      (resource === 'tool-grants' && request.method === 'DELETE');
    return allowed && noQuery(target)
      ? endpoint('workspace', tenantId, projectId, workspaceId)
      : null;
  }
  return null;
}

function authorizeProjectCohort(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): CloudProductEndpoint | null {
  if (segments[3] !== 'projects' || segments.length < 6) return null;
  const projectId = requiredIdentifier(segments[4]);
  const resource = segments[5];
  if (resource === 'my-work') {
    return segments.length === 6 && request.method === 'GET' && noQuery(target)
      ? endpoint('project', null, projectId, null)
      : null;
  }
  if (resource === 'cron-jobs') {
    return authorizeCronEndpoint(request, target, segments)
      ? endpoint('project', null, projectId, null)
      : null;
  }
  if (resource === 'sandbox') {
    return authorizeSandboxEndpoint(request, target, segments)
      ? endpoint('project', null, projectId, null)
      : null;
  }
  return null;
}

function authorizeCronEndpoint(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): boolean {
  if (segments.length === 6) {
    if (request.method === 'GET') return exactQueryKeys(target.searchParams, CRON_COLLECTION_QUERY);
    return request.method === 'POST' && noQuery(target);
  }
  if (segments.length === 7 && segments[6] === 'capabilities') {
    return request.method === 'GET' && noQuery(target);
  }
  if (segments.length === 7) {
    requiredIdentifier(segments[6]);
    return (
      (request.method === 'GET' || request.method === 'PATCH' || request.method === 'DELETE') &&
      noQuery(target)
    );
  }
  if (segments.length === 8) {
    requiredIdentifier(segments[6]);
    if (segments[7] === 'toggle') return request.method === 'POST' && noQuery(target);
    if (segments[7] === 'run') return request.method === 'POST' && noQuery(target);
    if (segments[7] === 'runs') {
      return request.method === 'GET' && exactQueryKeys(target.searchParams, CRON_RUNS_QUERY);
    }
  }
  return false;
}

function authorizeSandboxEndpoint(
  request: EndpointRequest,
  target: URL,
  segments: readonly string[],
): boolean {
  if (segments.length === 6) return request.method === 'GET' && noQuery(target);
  if (segments.length === 7 && segments[6] === 'files' && request.method === 'GET') {
    return allowedQueryKeys(
      target.searchParams,
      new Set(['path', 'limit', 'cursor']),
      ['path', 'limit'],
    );
  }
  if (
    segments.length === 8 &&
    segments[6] === 'files' &&
    segments[7] === 'content' &&
    request.method === 'GET'
  ) {
    return allowedQueryKeys(
      target.searchParams,
      new Set(['path', 'max_bytes']),
      ['path', 'max_bytes'],
    );
  }
  if (
    segments.length === 7 &&
    segments[6] === 'capabilities' &&
    request.method === 'GET' &&
    noQuery(target)
  ) {
    return true;
  }
  if (
    segments.length === 8 &&
    segments[6] === 'desktop' &&
    segments[7] === 'session' &&
    request.method === 'POST' &&
    exactQueryKeys(target.searchParams, new Set(['resolution'])) &&
    ['1280x720', '1600x900', '1920x1080', '2560x1440'].includes(
      target.searchParams.get('resolution') ?? '',
    )
  ) {
    return true;
  }
  if (
    segments.length === 8 &&
    segments[6] === 'terminal' &&
    segments[7] === 'sessions' &&
    request.method === 'POST' &&
    noQuery(target)
  ) {
    return true;
  }
  if (
    segments.length === 10 &&
    segments[6] === 'terminal' &&
    segments[7] === 'sessions' &&
    segments[9] === 'resume' &&
    request.method === 'POST' &&
    noQuery(target)
  ) {
    requiredIdentifier(segments[8]);
    return true;
  }
  if (segments.length !== 7 || !noQuery(target)) return false;
  return (
    (segments[6] === 'execute' && request.method === 'POST') ||
    (segments[6] === 'proxy-auth-cookie' && request.method === 'POST') ||
    (segments[6] === 'terminal' && request.method === 'POST')
  );
}

function exactCatalogQuery(
  query: URLSearchParams,
  keys: ReadonlySet<string>,
  tenantRequired: boolean,
): boolean {
  if (!exactQueryKeys(query, keys)) return false;
  if (query.get('page') !== '1' || query.get('page_size') !== '100') return false;
  if (tenantRequired) requiredIdentifier(query.get('tenant_id'));
  return true;
}

function exactQueryKeys(query: URLSearchParams, keys: ReadonlySet<string>): boolean {
  const entries = [...query.entries()];
  if (entries.length !== keys.size) return false;
  const observed = new Set<string>();
  for (const [key, value] of entries) {
    if (!keys.has(key) || observed.has(key) || !validQueryValue(value)) return false;
    observed.add(key);
  }
  return observed.size === keys.size;
}

function allowedQueryKeys(
  query: URLSearchParams,
  allowed: ReadonlySet<string>,
  required: readonly string[],
): boolean {
  const entries = [...query.entries()];
  const observed = new Set<string>();
  for (const [key, value] of entries) {
    if (!allowed.has(key) || observed.has(key) || !validQueryValue(value)) return false;
    observed.add(key);
  }
  return required.every((key) => observed.has(key));
}

function noQuery(target: URL): boolean {
  return [...target.searchParams].length === 0;
}

function validQueryValue(value: string): boolean {
  return value.length > 0 && value.length <= 512 && value === value.trim() && !hasControl(value);
}

function requiredIdentifier(value: string | null | undefined): string {
  if (!value) throw new Error('cloud request endpoint is not allowed');
  let decoded: string;
  try {
    decoded = decodeURIComponent(value);
  } catch {
    throw new Error('cloud request endpoint is not allowed');
  }
  if (
    decoded.length === 0 ||
    decoded.length > 256 ||
    decoded !== decoded.trim() ||
    hasControl(decoded)
  ) {
    throw new Error('cloud request endpoint is not allowed');
  }
  return decoded;
}

function optionalIdentifier(value: string | null | undefined): string | null {
  return value == null ? null : requiredIdentifier(value);
}

function requiredBodyIdentifier(
  body: Readonly<Record<string, unknown>> | undefined,
  key: string,
): string {
  return requiredIdentifier(typeof body?.[key] === 'string' ? body[key] : null);
}

function endpoint(
  kind: CloudProductEndpoint['kind'],
  tenantId: string | null,
  projectId: string | null,
  workspaceId: string | null,
): CloudProductEndpoint {
  return Object.freeze({ kind, tenantId, projectId, workspaceId });
}

function hasControl(value: string): boolean {
  return Array.from(value).some((character) => {
    const code = character.codePointAt(0) ?? 0;
    return code <= 0x1f || code === 0x7f;
  });
}
