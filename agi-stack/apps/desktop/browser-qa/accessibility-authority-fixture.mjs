const AUTHORITY_ROLES = new Set(['admin', 'member']);

export function createAccessibilityAuthorityFixture(scope) {
  const tenantId = requireIdentifier(scope?.tenantId, 'accessibility_tenant_scope_required');
  const projectId = requireIdentifier(scope?.projectId, 'accessibility_project_scope_required');
  const workspaceId = requireIdentifier(
    scope?.workspaceId,
    'accessibility_workspace_scope_required',
  );
  let role = 'admin';
  let authorityRevision = 1;
  let resolvedRequests = 0;

  return Object.freeze({
    setRole(nextRole) {
      if (!AUTHORITY_ROLES.has(nextRole)) {
        throw new Error('accessibility_authority_role_invalid');
      }
      if (role !== nextRole) authorityRevision += 1;
      role = nextRole;
    },
    resolve(request) {
      const response = resolveAccessibilityAuthorityResponse(request, {
        tenantId,
        projectId,
        workspaceId,
        role,
        authorityRevision,
      });
      if (response !== null) resolvedRequests += 1;
      return response;
    },
    observation() {
      return Object.freeze({ role, authorityRevision, resolvedRequests });
    },
  });
}

export function resolveAccessibilityAuthorityResponse(request, authority) {
  const method = typeof request?.method === 'string' ? request.method.toUpperCase() : '';
  const url = new URL(request?.url);
  const tenantId = requireIdentifier(
    authority?.tenantId,
    'accessibility_tenant_scope_required',
  );
  const projectId = requireIdentifier(
    authority?.projectId,
    'accessibility_project_scope_required',
  );
  const workspaceId = requireIdentifier(
    authority?.workspaceId,
    'accessibility_workspace_scope_required',
  );
  const role = AUTHORITY_ROLES.has(authority?.role) ? authority.role : null;
  if (role === null) throw new Error('accessibility_authority_role_invalid');
  const authorityRevision = authority?.authorityRevision;
  if (!Number.isSafeInteger(authorityRevision) || authorityRevision < 0) {
    throw new Error('accessibility_authority_revision_invalid');
  }
  const path = url.pathname;

  if (method === 'POST' && path === '/api/v1/auth/token') {
    return response({
      access_token: `ms_sk_${'a'.repeat(64)}`,
      token_type: 'bearer',
      must_change_password: false,
    });
  }
  if (method === 'GET' && path === '/api/v1/auth/me') {
    const admin = role === 'admin';
    return response({
      user_id: `accessibility-${role}`,
      email: `${role}@accessibility.invalid`,
      name: `Accessibility ${role}`,
      roles: [role],
      global_roles: admin ? ['system_admin'] : [],
      is_superuser: admin,
      is_active: true,
    });
  }
  if (method === 'GET' && path === '/api/v1/workspace-context') {
    return response({
      context: {
        tenant_id: tenantId,
        project_id: projectId,
        revision: authorityRevision,
        updated_at: '2026-01-01T00:00:00Z',
      },
      membership_role: role,
    });
  }
  if (method === 'GET' && path === '/api/v1/tenants') {
    return response({
      tenants: [{ id: tenantId, name: 'Accessibility tenant', plan: 'enterprise' }],
      total: 1,
      page: 1,
      page_size: 100,
    });
  }
  if (method === 'GET' && path === '/api/v1/admin/dlq/messages') {
    return response({
      messages: [],
      total: 0,
      limit: Number(url.searchParams.get('limit') ?? 50),
      offset: Number(url.searchParams.get('offset') ?? 0),
      authority_revision: authorityRevision,
    });
  }
  if (method === 'GET' && path === '/api/v1/admin/dlq/stats') {
    return response({
      total_messages: 0,
      pending_count: 0,
      retrying_count: 0,
      discarded_count: 0,
      expired_count: 0,
      resolved_count: 0,
      oldest_message_age_seconds: 0,
      error_type_counts: {},
      event_type_counts: {},
    });
  }
  if (method === 'GET' && path === '/api/v1/projects') {
    return response({
      projects: [
        {
          id: projectId,
          tenant_id: tenantId,
          name: 'Accessibility project',
          owner_id: 'accessibility-admin',
        },
      ],
      total: 1,
      page: 1,
      page_size: 100,
    });
  }
  if (method === 'GET' && path === '/api/v1/projects/') {
    return response({
      projects: [
        {
          id: projectId,
          tenant_id: tenantId,
          name: 'Accessibility project',
          description: 'Deterministic accessibility authority project',
          owner_id: 'accessibility-admin',
          member_ids: [`accessibility-${role}`],
          is_public: false,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: null,
          stats: {},
        },
      ],
      total: 1,
      page: Number(url.searchParams.get('page') ?? 1),
      page_size: Number(url.searchParams.get('page_size') ?? 20),
      owner_ids: ['accessibility-admin'],
    });
  }
  if (
    method === 'GET' &&
    path === `/api/v1/projects/${encodeURIComponent(projectId)}` &&
    (!url.searchParams.has('tenant_id') || url.searchParams.get('tenant_id') === tenantId)
  ) {
    return response({
      id: projectId,
      tenant_id: tenantId,
      name: 'Accessibility project',
      description: 'Deterministic accessibility authority project',
      owner_id: 'accessibility-admin',
      is_public: false,
      memory_rules: {
        max_episodes: 1000,
        retention_days: 365,
        auto_refresh: true,
        refresh_interval: 60,
      },
      graph_config: {
        max_nodes: 10000,
        max_edges: 50000,
        similarity_threshold: 0.8,
        community_detection: true,
      },
      sandbox_config: { sandbox_type: 'docker' },
      agent_conversation_mode: 'workspace',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: null,
    });
  }
  if (
    method === 'GET' &&
    path === `/api/v1/projects/${encodeURIComponent(projectId)}/stats`
  ) {
    return response({
      tenant_id: tenantId,
      project_id: projectId,
      memory_count: 0,
      storage_used: 0,
      storage_limit: 1024,
      active_nodes: 0,
      collaborators: 1,
    });
  }
  if (
    method === 'GET' &&
    (path === `/api/v1/projects/${encodeURIComponent(projectId)}/sandbox` ||
      path === `/api/v1/projects/${encodeURIComponent(projectId)}/sandbox/stats`)
  ) {
    return response(
      {
        detail: 'project_sandbox_not_configured',
        reason_code: 'project_sandbox_not_configured',
      },
      404,
    );
  }
  if (method === 'GET' && path === '/api/v1/search-enhanced/capabilities') {
    return response({
      service_version: '0.1.0',
      contract_version: '2.1.0',
      graph_backend: {
        status: 'available',
        reason_code: null,
        retryable: false,
        allowed_actions: ['search', 'traverse', 'rebuild_communities'],
      },
      search_types: {
        semantic: {
          description: 'Semantic search using embeddings and hybrid retrieval',
          endpoint: '/api/v1/memory/search',
          parameters: {
            query: 'string (required)',
            limit: 'integer (1-100)',
            tenant_id: 'string (optional)',
            project_id: 'string (optional)',
          },
        },
        advanced: {
          description: 'Advanced search with configurable strategy and reranking',
          endpoint: '/api/v1/search-enhanced/advanced',
          parameters: {
            query: 'string (required)',
            strategy: 'string (optional)',
            focal_node_uuid: 'string (optional)',
            reranker: 'string (optional)',
            limit: 'integer (1-200)',
            tenant_id: 'string (optional)',
            project_id: 'string (optional)',
            since: 'ISO datetime string (optional)',
          },
        },
        graph_traversal: {
          description: 'Search by traversing the knowledge graph',
          endpoint: '/api/v1/search-enhanced/graph-traversal',
          parameters: {
            start_entity_uuid: 'string (required)',
            max_depth: 'integer (1-5)',
            relationship_types: 'array of strings (optional)',
            limit: 'integer (1-200)',
          },
        },
        community: {
          description: 'Search within a specific community',
          endpoint: '/api/v1/search-enhanced/community',
          parameters: {
            community_uuid: 'string (required)',
            limit: 'integer (1-200)',
            include_episodes: 'boolean',
            tenant_id: 'string (optional)',
            project_id: 'string (optional)',
          },
        },
        temporal: {
          description: 'Search within a time range',
          endpoint: '/api/v1/search-enhanced/temporal',
          parameters: {
            query: 'string (required)',
            since: 'ISO datetime string (optional)',
            until: 'ISO datetime string (optional)',
            limit: 'integer (1-200)',
          },
        },
        faceted: {
          description: 'Search with faceted filtering',
          endpoint: '/api/v1/search-enhanced/faceted',
          parameters: {
            query: 'string (required)',
            entity_types: 'array of strings (optional)',
            tags: 'array of strings (optional)',
            since: 'ISO datetime string (optional)',
            limit: 'integer (1-200)',
            offset: 'integer (0+)',
          },
        },
      },
      filters: {
        entity_types: [
          'Person',
          'Organization',
          'Product',
          'Location',
          'Event',
          'Concept',
          'Custom',
        ],
        relationship_types: [
          'RELATES_TO',
          'MENTIONS',
          'PART_OF',
          'CONTAINS',
          'BELONGS_TO',
          'OWNS',
          'LOCATED_AT',
        ],
      },
    });
  }
  if (
    method === 'GET' &&
    path ===
      `/api/v1/projects/${encodeURIComponent(projectId)}/cron-jobs/capabilities`
  ) {
    const runtimeUnavailable = {
      allowed: false,
      reason_code: 'durable_automation_runtime_unavailable',
    };
    return response({
      service_version: '0.1.0',
      contract_version: '2.0.0',
      schema_version: 1,
      read: true,
      revision_guarded: false,
      idempotency_guarded: false,
      durable_execution: false,
      supported_read_trigger_kinds: ['manual', 'schedule', 'event'],
      create: runtimeUnavailable,
      edit: runtimeUnavailable,
      toggle: runtimeUnavailable,
      run_now: {
        allowed: false,
        reason_code: 'durable_automation_execution_unavailable',
      },
      delete: runtimeUnavailable,
    });
  }
  if (
    method === 'GET' &&
    path === `/api/v1/projects/${encodeURIComponent(projectId)}/cron-jobs`
  ) {
    return response({ items: [], total: 0 });
  }
  if (
    method === 'GET' &&
    path ===
      `/api/v1/agent/trace/runs/project/${encodeURIComponent(projectId)}/active/count`
  ) {
    return response({ project_id: projectId, active_count: 0 });
  }
  if (
    method === 'GET' &&
    path === `/api/v1/agent/trace/runs/project/${encodeURIComponent(projectId)}`
  ) {
    return response({ project_id: projectId, runs: [], total: 0 });
  }
  if (
    method === 'GET' &&
    path === `/api/v1/agent/workflows/patterns/project/${encodeURIComponent(projectId)}`
  ) {
    return response({
      project_id: projectId,
      tenant_id: tenantId,
      scope_kind: 'tenant_shared',
      patterns: [],
      total: 0,
      page: Number(url.searchParams.get('page') ?? 1),
      page_size: Number(url.searchParams.get('page_size') ?? 100),
    });
  }
  if (
    method === 'GET' &&
    [
      `/api/v1/projects/${encodeURIComponent(projectId)}/schema/entities`,
      `/api/v1/projects/${encodeURIComponent(projectId)}/schema/edges`,
      `/api/v1/projects/${encodeURIComponent(projectId)}/schema/mappings`,
    ].includes(path)
  ) {
    return response([]);
  }
  if (
    method === 'GET' &&
    path === '/api/v1/memories/' &&
    url.searchParams.get('project_id') === projectId &&
    url.searchParams.get('page') === '1' &&
    ['5', '50'].includes(url.searchParams.get('page_size') ?? '')
  ) {
    const pageSize = Number(url.searchParams.get('page_size'));
    return response({
      tenant_id: tenantId,
      project_id: projectId,
      memories: [],
      total: 0,
      page: 1,
      page_size: pageSize,
    });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/graph/entities/' &&
    url.searchParams.get('tenant_id') === tenantId &&
    url.searchParams.get('project_id') === projectId &&
    url.searchParams.get('limit') === '50' &&
    url.searchParams.get('offset') === '0'
  ) {
    return response({ entities: [], total: 0, limit: 50, offset: 0 });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/graph/entities/types' &&
    url.searchParams.get('tenant_id') === tenantId &&
    url.searchParams.get('project_id') === projectId
  ) {
    return response({ entity_types: [], total: 0 });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/graph/communities/' &&
    url.searchParams.get('tenant_id') === tenantId &&
    url.searchParams.get('project_id') === projectId &&
    url.searchParams.get('limit') === '50' &&
    url.searchParams.get('offset') === '0'
  ) {
    return response({ communities: [], total: 0, limit: 50, offset: 0 });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/graph/memory/graph' &&
    url.searchParams.get('tenant_id') === tenantId &&
    url.searchParams.get('project_id') === projectId &&
    url.searchParams.get('limit') === '1000'
  ) {
    return response({ elements: { nodes: [], edges: [] } });
  }
  if (
    method === 'GET' &&
    path === `/api/v1/projects/${encodeURIComponent(projectId)}/members`
  ) {
    return response({
      members: [
        {
          user_id: `accessibility-${role}`,
          email: `${role}@accessibility.invalid`,
          name: `Accessibility ${role}`,
          role: role === 'admin' ? 'owner' : 'member',
          permissions: { read: true, write: role === 'admin' },
          created_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
    });
  }
  if (method === 'GET' && path === '/api/v1/agent/bindings') {
    return response([]);
  }
  if (method === 'GET' && path === '/api/v1/agent/definitions') {
    const requestedProjectId = url.searchParams.get('project_id');
    const definitions = [
      {
        id: 'accessibility-agent',
        tenant_id: tenantId,
        project_id: requestedProjectId,
        name: 'accessibility-agent',
        display_name: 'Accessibility agent',
        enabled: true,
      },
    ];
    return url.searchParams.get('include_total') === 'true'
      ? response({
          definitions,
          total: definitions.length,
          limit: Number(url.searchParams.get('limit') ?? 100),
          offset: Number(url.searchParams.get('offset') ?? 0),
          authority_revision: authorityRevision,
        })
      : response(definitions);
  }
  if (
    method === 'GET' &&
    path === '/api/v1/agent/config' &&
    url.searchParams.get('tenant_id') === tenantId
  ) {
    return response({
      id: `accessibility-agent-config-${tenantId}`,
      tenant_id: tenantId,
      config_type: 'tenant',
      llm_model: 'accessibility-fixture-model',
      llm_temperature: 0.2,
      pattern_learning_enabled: true,
      multi_level_thinking_enabled: false,
      max_work_plan_steps: 10,
      tool_timeout_seconds: 60,
      enabled_tools: [],
      disabled_tools: [],
      runtime_hooks: [],
      runtime_hook_settings_redacted: false,
      multi_agent_enabled: true,
      authority_revision: authorityRevision,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/agent/config/can-modify' &&
    url.searchParams.get('tenant_id') === tenantId
  ) {
    return response({ can_modify: role === 'admin' });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/agent/config/hooks/catalog' &&
    url.searchParams.get('tenant_id') === tenantId
  ) {
    return response({ hooks: [] });
  }
  if (
    method === 'GET' &&
    path === `/api/v1/agent/trace/runs/tenant/${encodeURIComponent(tenantId)}`
  ) {
    return response({ tenant_id: tenantId, runs: [], total: 0 });
  }
  if (
    method === 'GET' &&
    path ===
      `/api/v1/agent/trace/runs/tenant/${encodeURIComponent(tenantId)}/active/count`
  ) {
    return response({ tenant_id: tenantId, active_count: 0 });
  }
  if (
    method === 'GET' &&
    path ===
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/projects/${encodeURIComponent(projectId)}/workspaces`
  ) {
    return response([
      {
        id: workspaceId,
        tenant_id: tenantId,
        project_id: projectId,
        name: 'Accessibility workspace',
      },
    ]);
  }
  const workspacePath =
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/projects/${encodeURIComponent(projectId)}` +
    `/workspaces/${encodeURIComponent(workspaceId)}`;
  if (method === 'GET' && path === `${workspacePath}/collaboration/authority`) {
    return response({
      contract_version: '2.0.0',
      tenant_id: tenantId,
      project_id: projectId,
      workspace_id: workspaceId,
      revision: authorityRevision,
      cursor: `accessibility-workspace-revision-${authorityRevision}`,
    });
  }
  if (method === 'GET' && path === `${workspacePath}/objectives`) {
    return response([]);
  }
  if (method === 'GET' && path === `${workspacePath}/messages`) {
    return response([]);
  }
  if (method === 'GET' && path === `${workspacePath}/members`) {
    return response([]);
  }
  if (method === 'GET' && path === `${workspacePath}/agents`) {
    return response([]);
  }
  if (
    method === 'GET' &&
    path === `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/tasks`
  ) {
    return response([]);
  }
  if (
    method === 'GET' &&
    path === `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/plan`
  ) {
    return response({ detail: 'accessibility_plan_not_created' }, 404);
  }
  if (
    method === 'GET' &&
    path === '/api/v1/agent/conversations' &&
    url.searchParams.get('project_id') === projectId
  ) {
    return response({
      items: [],
      total: 0,
      has_more: false,
      offset: Number(url.searchParams.get('offset') ?? 0),
      limit: Number(url.searchParams.get('limit') ?? 100),
      next_offset: null,
    });
  }
  if (
    method === 'GET' &&
    path === `/api/v1/projects/${encodeURIComponent(projectId)}/my-work`
  ) {
    return response({ items: [], total: 0, limit: 50, offset: 0, next_offset: null });
  }
  if (
    method === 'GET' &&
    path === `/api/v1/tenants/${encodeURIComponent(tenantId)}/audit-logs`
  ) {
    return response({
      items: [],
      total: 0,
      limit: Number(url.searchParams.get('limit') ?? 20),
      offset: Number(url.searchParams.get('offset') ?? 0),
      authority_revision: authorityRevision,
    });
  }
  if (
    method === 'GET' &&
    path ===
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/audit-logs/runtime-hooks/summary`
  ) {
    return response({
      total: 0,
      action_counts: {},
      executor_counts: {},
      family_counts: {},
      isolation_mode_counts: {},
      latest_timestamp: null,
      authority_revision: authorityRevision,
    });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/tasks/authority-revision' &&
    url.searchParams.get('tenant_id') === tenantId
  ) {
    return response({
      tenant_id: tenantId,
      authority_revision: authorityRevision,
    });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/tasks/stats' &&
    url.searchParams.get('tenant_id') === tenantId
  ) {
    return response({
      total: 0,
      pending: 0,
      processing: 0,
      completed: 0,
      failed: 0,
      throughput_per_minute: 0,
      error_rate: 0,
    });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/tasks/queue-depth' &&
    url.searchParams.get('tenant_id') === tenantId
  ) {
    return response([]);
  }
  if (
    method === 'GET' &&
    path === '/api/v1/tasks/recent' &&
    url.searchParams.get('tenant_id') === tenantId
  ) {
    const limit = Number(url.searchParams.get('limit') ?? 50);
    const offset = Number(url.searchParams.get('offset') ?? 0);
    return response({
      tasks: [],
      total: 0,
      limit,
      offset,
      has_more: false,
    });
  }
  if (
    method === 'GET' &&
    path === `/api/v1/tenants/${encodeURIComponent(tenantId)}/analytics` &&
    url.searchParams.get('period') === '30d'
  ) {
    return response({
      authority_revision: authorityRevision,
      memoryGrowth: [],
      projectStorage: [],
      summary: {
        total_memories: 0,
        total_storage_bytes: 0,
        total_projects: 0,
        period_days: 30,
      },
    });
  }
  if (method === 'GET' && path === `/api/v1/tenants/${encodeURIComponent(tenantId)}`) {
    return response({
      id: tenantId,
      name: 'Accessibility tenant',
      slug: 'accessibility-tenant',
      description: 'Deterministic accessibility authority tenant',
      owner_id: 'accessibility-admin',
      plan: 'enterprise',
      max_projects: 10,
      max_users: 50,
      max_storage: 1024,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: null,
    });
  }
  if (
    method === 'GET' &&
    path === `/api/v1/tenants/${encodeURIComponent(tenantId)}/stats`
  ) {
    return response({
      authority_revision: authorityRevision,
      tenant_info: {
        organization_id: 'Accessibility QA',
        plan: 'enterprise',
        region: 'test',
        next_billing_date: null,
      },
      storage: { used: 0, total: 1024, percentage: 0 },
      projects: { active: 0, new_this_week: 0, list: [] },
      members: { total: 1, new_added: 0 },
      memory_history: [],
    });
  }
  if (
    method === 'GET' &&
    path === `/api/v1/tenants/${encodeURIComponent(tenantId)}/registries`
  ) {
    return response([]);
  }
  if (
    method === 'GET' &&
    path === `/api/v1/tenants/${encodeURIComponent(tenantId)}/smtp-config`
  ) {
    return response(null);
  }
  if (
    method === 'GET' &&
    path === `/api/v1/tenants/${encodeURIComponent(tenantId)}/gene-policies`
  ) {
    return response([]);
  }
  if (method === 'GET' && path === '/api/v1/skills/') {
    const skills = [
      {
        id: 'accessibility-skill',
        tenant_id: tenantId,
        project_id: projectId,
        name: 'accessibility-skill',
        description: 'Deterministic accessibility skill',
        tools: [],
        status: 'active',
        scope: 'project',
        is_system_skill: false,
        source: 'database',
        revision: 0,
      },
    ];
    return response({
      skills,
      total: skills.length,
      authority_revision: authorityRevision,
    });
  }
  if (
    method === 'GET' &&
    path === `/api/v1/channels/tenants/${encodeURIComponent(tenantId)}/plugins`
  ) {
    return response({
      items: [],
      diagnostics: [],
      authority_revision: authorityRevision,
    });
  }
  if (
    method === 'GET' &&
    path ===
      `/api/v1/channels/tenants/${encodeURIComponent(tenantId)}/plugins/channel-catalog`
  ) {
    return response({ items: [] });
  }
  if (
    method === 'GET' &&
    path === `/api/v1/channels/projects/${encodeURIComponent(projectId)}/configs`
  ) {
    return response({ items: [] });
  }
  const matchesProjectMaintenanceScope =
    url.searchParams.get('tenant_id') === tenantId &&
    url.searchParams.get('project_id') === projectId;
  if (
    method === 'GET' &&
    path === '/api/v1/maintenance/status' &&
    matchesProjectMaintenanceScope
  ) {
    return response({
      stats: { entities: 0, episodes: 0, communities: 0, old_episodes: 0 },
      recommendations: [],
      last_checked: '2026-01-01T00:00:00Z',
    });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/data/stats' &&
    matchesProjectMaintenanceScope
  ) {
    return response({
      entity_count: 0,
      episodic_count: 0,
      community_count: 0,
      edge_count: 0,
    });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/maintenance/embeddings/status' &&
    matchesProjectMaintenanceScope
  ) {
    return response({
      current_provider: 'accessibility-fixture',
      current_dimension: 0,
      existing_dimension: 0,
      is_compatible: true,
      missing_embeddings: 0,
    });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/mcp' &&
    url.searchParams.get('project_id') === projectId
  ) {
    return response({
      servers: [],
      authority_revision: authorityRevision,
    });
  }
  if (
    method === 'GET' &&
    path === `/api/v1/acp/tenants/${encodeURIComponent(tenantId)}/status`
  ) {
    return response({
      enabled: true,
      websocketEnabled: true,
      httpBaseUrl: 'https://accessibility.invalid/api/v1/acp',
      agentCount: 0,
      availableCount: 0,
      activeSessionCount: 0,
      agents: [],
      sessions: [],
    });
  }
  if (
    method === 'GET' &&
    path === `/api/v1/acp/tenants/${encodeURIComponent(tenantId)}/runner-pools`
  ) {
    return response([]);
  }
  if (
    method === 'GET' &&
    path === `/api/v1/tenant-webhooks/${encodeURIComponent(tenantId)}`
  ) {
    return response([]);
  }
  if (
    method === 'GET' &&
    path === `/api/v1/tenants/${encodeURIComponent(tenantId)}/members`
  ) {
    return response({
      members: [
        {
          user_id: `accessibility-${role}`,
          email: `${role}@accessibility.invalid`,
          name: `Accessibility ${role}`,
          role: role === 'admin' ? 'owner' : 'member',
          permissions: { read: true, write: role === 'admin' },
          created_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
      authority_revision: authorityRevision,
    });
  }
  if (
    method === 'GET' &&
    path === `/api/v1/tenants/${encodeURIComponent(tenantId)}/trust/policies` &&
    url.searchParams.get('workspace_id')
  ) {
    return response({ items: [], authority_revision: authorityRevision });
  }
  if (
    method === 'GET' &&
    path === `/api/v1/tenants/${encodeURIComponent(tenantId)}/trust/decision-records` &&
    url.searchParams.get('workspace_id') === workspaceId
  ) {
    return response({ items: [], authority_revision: authorityRevision });
  }
  if (
    method === 'GET' &&
    path === `/api/v1/tenants/${encodeURIComponent(tenantId)}/billing`
  ) {
    return response({
      tenant: {
        id: tenantId,
        name: 'Accessibility tenant',
        plan: 'enterprise',
        storage_limit: 1024,
      },
      usage: { projects: 1, memories: 0, users: 1, storage: 0 },
      invoices: [],
      authority_revision: authorityRevision,
    });
  }
  if (
    method === 'GET' &&
    path === `/api/v1/tenants/${encodeURIComponent(tenantId)}/invoices`
  ) {
    return response({ invoices: [], authority_revision: authorityRevision });
  }
  if (
    method === 'GET' &&
    role === 'admin' &&
    path === `/api/v1/tenants/${encodeURIComponent(tenantId)}/invitations`
  ) {
    return response({
      items: [],
      total: 0,
      limit: Number(url.searchParams.get('limit') ?? 50),
      offset: Number(url.searchParams.get('offset') ?? 0),
    });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/genes/' &&
    url.searchParams.get('tenant_id') === tenantId
  ) {
    return response({
      genes: [],
      total: 0,
      page: Number(url.searchParams.get('page') ?? 1),
      page_size: Number(url.searchParams.get('page_size') ?? 20),
      authority_revision: authorityRevision,
    });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/events/types' &&
    url.searchParams.get('tenant_id') === tenantId
  ) {
    return response(['agent.run.completed']);
  }
  if (
    method === 'GET' &&
    path === '/api/v1/events' &&
    url.searchParams.get('tenant_id') === tenantId
  ) {
    return response({
      items: [],
      total: 0,
      page: Number(url.searchParams.get('page') ?? 1),
      page_size: Number(url.searchParams.get('page_size') ?? 20),
      authority_revision: authorityRevision,
    });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/admin/pool/status' &&
    url.searchParams.get('scope') === 'tenant' &&
    url.searchParams.get('tenant_id') === tenantId
  ) {
    if (role !== 'admin') {
      return response({ detail: 'global_admin_required' }, 403);
    }
    return response({
      enabled: true,
      status: 'running',
      total_instances: 0,
      hot_instances: 0,
      warm_instances: 0,
      cold_instances: 0,
      ready_instances: 0,
      executing_instances: 0,
      unhealthy_instances: 0,
      prewarm_pool: null,
      resource_usage: null,
      resolved_scope: 'tenant',
      tenant_id: tenantId,
      reason_code: 'global_pool_capacity_not_available_in_tenant_scope',
      authority_revision: authorityRevision,
    });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/admin/pool/instances' &&
    url.searchParams.get('scope') === 'tenant' &&
    url.searchParams.get('tenant_id') === tenantId
  ) {
    if (role !== 'admin') {
      return response({ detail: 'global_admin_required' }, 403);
    }
    return response({
      instances: [],
      total: 0,
      page: Number(url.searchParams.get('page') ?? 1),
      page_size: Number(url.searchParams.get('page_size') ?? 100),
      resolved_scope: 'tenant',
      tenant_id: tenantId,
    });
  }
  if (method === 'GET' && path === '/api/v1/instances/') {
    return response({
      instances: [],
      total: 0,
      page: Number(url.searchParams.get('page') ?? 1),
      page_size: Number(url.searchParams.get('page_size') ?? 20),
      authority_revision: authorityRevision,
    });
  }
  if (method === 'GET' && path === '/api/v1/clusters/') {
    return response({
      clusters: [],
      total: 0,
      page: Number(url.searchParams.get('page') ?? 1),
      page_size: Number(url.searchParams.get('page_size') ?? 20),
      authority_revision: authorityRevision,
    });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/deploys/' &&
    url.searchParams.get('tenant_id') === tenantId
  ) {
    return response({
      deploys: [],
      total: 0,
      page: Number(url.searchParams.get('page') ?? 1),
      page_size: Number(url.searchParams.get('page_size') ?? 20),
      authority_revision: authorityRevision,
    });
  }
  if (method === 'GET' && path === '/api/v1/instance-templates/') {
    return response({
      templates: [],
      total: 0,
      page: Number(url.searchParams.get('page') ?? 1),
      page_size: Number(url.searchParams.get('page_size') ?? 20),
      authority_revision: authorityRevision,
    });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/projects/sandboxes' &&
    url.searchParams.get('limit') === '100' &&
    url.searchParams.get('offset') === '0'
  ) {
    return response({ sandboxes: [], total: 0 });
  }
  if (method === 'GET' && path === '/api/v1/llm-providers/authority-snapshot') {
    return response({
      providers: [],
      types: [
        {
          provider_type: 'openai',
          operation_type: 'llm',
          probe_supported: true,
          auth_methods: ['api_key'],
          unavailable_auth_methods: ['environment', 'oauth'],
        },
      ],
      authority_revision: authorityRevision,
    });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/subagents/templates/list' &&
    url.searchParams.get('tenant_id') === tenantId
  ) {
    return response({
      templates: [],
      total: 0,
      categories: [],
      authority_revision: authorityRevision,
    });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/skills/evolution/overview' &&
    url.searchParams.get('tenant_id') === tenantId
  ) {
    return response({
      authority_revision: authorityRevision,
      stats: {
        total_sessions: 0,
        skill_sessions: 0,
        no_skill_sessions: 0,
        unprocessed_sessions: 0,
        processed_sessions: 0,
        scored_sessions: 0,
        successful_sessions: 0,
        avg_score: null,
        total_jobs: 0,
        pending_jobs: 0,
        applied_jobs: 0,
        skipped_jobs: 0,
        rejected_jobs: 0,
      },
      monitor: {
        refresh_interval_seconds: 30,
        latest_session_at: null,
        latest_job_at: null,
        backlog_count: 0,
        unscored_count: 0,
        blocked_by_review_count: 0,
        eligible_skill_count: 0,
        needs_attention: false,
      },
      stages: [],
      skills: [],
      recent_sessions: [],
      recent_jobs: [],
      trigger: {
        enabled: true,
        capture_hook: 'after_turn_complete',
        minimum_sessions: 3,
        scoring_minimum_sessions: 2,
        minimum_average_score: 0.75,
        max_sessions_per_batch: 20,
        interval_minutes: 30,
        publish_mode: 'review',
        auto_apply: false,
        manual_trigger: '/api/v1/skills/{skill_id}/evolution/run',
      },
    });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/skills/evolution/config' &&
    url.searchParams.get('tenant_id') === tenantId
  ) {
    return response({
      enabled: true,
      min_sessions_per_skill: 3,
      scoring_min_sessions_per_skill: 2,
      min_avg_score: 0.75,
      max_sessions_per_batch: 20,
      evolution_interval_minutes: 30,
      publish_mode: 'review',
      auto_apply: false,
    });
  }
  if (
    method === 'GET' &&
    path === '/api/v1/agent/workflows/patterns' &&
    url.searchParams.get('tenant_id') === tenantId
  ) {
    return response({
      patterns: [],
      total: 0,
      page: Number(url.searchParams.get('page') ?? 1),
      page_size: Number(url.searchParams.get('page_size') ?? 20),
    });
  }
  return null;
}

function response(body, status = 200) {
  return Object.freeze({ status, body: Object.freeze(body) });
}

function requireIdentifier(value, reasonCode) {
  if (typeof value !== 'string' || value.length === 0 || value.trim() !== value) {
    throw new Error(reasonCode);
  }
  return value;
}
