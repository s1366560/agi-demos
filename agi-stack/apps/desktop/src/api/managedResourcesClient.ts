import { parseDocument } from 'yaml';

import type {
  DesktopRuntimeConfig,
  ManagedAgentDefinition,
  ManagedAgentDefinitionMutation,
  ManagedExternalAcpAgent,
  ManagedSkill,
  ManagedSkillContent,
  ManagedSkillCreateMutation,
  ManagedSkillEvolutionDetail,
  ManagedSkillEvolutionJob,
  ManagedSkillEvolutionRun,
  ManagedSkillImportInput,
  ManagedSkillLifecycle,
  ManagedSkillMutation,
  ManagedSkillPackage,
  ManagedSkillVersionDetail,
  ManagedSkillVersionList,
  ManagedSkillZipImportInput,
  ManagedSubAgent,
  ManagedSubAgentMutation,
  ManagedSubAgentTemplateList,
  PromptTemplateCreateInput,
  PromptTemplateRecord,
  PromptTemplateVariable,
} from '../types';

type ManagedResourcesRequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
};

type ManagedResourcesErrorFactory = (message: string, status: number, payload: unknown) => Error;

export class ManagedResourcesClientError extends Error {
  readonly status: number;
  readonly payload: unknown;

  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = 'ManagedResourcesClientError';
    this.status = status;
    this.payload = payload;
  }
}

export class ManagedResourcesClient {
  private readonly config: DesktopRuntimeConfig;
  private readonly createError: ManagedResourcesErrorFactory;

  constructor(
    config: DesktopRuntimeConfig,
    createError: ManagedResourcesErrorFactory = (message, status, payload) =>
      new ManagedResourcesClientError(message, status, payload),
  ) {
    this.config = config;
    this.createError = createError;
  }

  async listManagedSkills(signal?: AbortSignal): Promise<ManagedSkill[]> {
    const params = new URLSearchParams({ limit: '100' });
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    if (this.config.projectId) params.set('project_id', this.config.projectId);
    const payload = await this.request<unknown>(`/api/v1/skills/?${params.toString()}`, {
      signal,
    });
    return readArray<ManagedSkill>(
      payload,
      ['skills', 'items', 'data'],
      'skills',
      this.createError,
    );
  }

  async setManagedSkillStatus(
    skillId: string,
    status: 'active' | 'disabled' | 'deprecated',
    expectedRevision?: number,
  ): Promise<ManagedSkill> {
    const params = new URLSearchParams({ status });
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    return this.request<ManagedSkill>(
      `/api/v1/skills/${encodeURIComponent(skillId)}/status?${params.toString()}`,
      {
        method: 'PATCH',
        body:
          this.config.mode === 'local'
            ? this.mutationBody({ status }, expectedRevision)
            : undefined,
      },
    );
  }

  async createManagedSkill(input: ManagedSkillCreateMutation): Promise<ManagedSkill> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkill>(`/api/v1/skills/?${params.toString()}`, {
      method: 'POST',
      body: this.mutationBody(input, 0, crypto.randomUUID()),
    });
  }

  async getManagedSkillContent(skillId: string): Promise<ManagedSkillContent> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkillContent>(
      `/api/v1/skills/${encodeURIComponent(skillId)}/content?${params.toString()}`,
    );
  }

  async updateManagedSkill(
    skillId: string,
    input: Omit<ManagedSkillMutation, 'full_content'>,
    expectedRevision?: number,
  ): Promise<ManagedSkill> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkill>(
      `/api/v1/skills/${encodeURIComponent(skillId)}?${params.toString()}`,
      { method: 'PUT', body: this.mutationBody(input, expectedRevision) },
    );
  }

  async updateManagedSkillContent(
    skillId: string,
    fullContent: string,
    expectedRevision?: number,
  ): Promise<ManagedSkill> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkill>(
      `/api/v1/skills/${encodeURIComponent(skillId)}/content?${params.toString()}`,
      {
        method: 'PUT',
        body: this.mutationBody({ full_content: fullContent }, expectedRevision),
      },
    );
  }

  async deleteManagedSkill(skillId: string, expectedRevision?: number): Promise<void> {
    const params = this.managedSkillTenantParams();
    await this.request<void>(
      `/api/v1/skills/${encodeURIComponent(skillId)}?${params.toString()}`,
      { method: 'DELETE', body: this.mutationBody(null, expectedRevision) },
    );
  }

  async importManagedSkillPackage(
    input: ManagedSkillImportInput,
  ): Promise<ManagedSkillLifecycle> {
    const params = this.managedSkillTenantParams();
    if (this.config.mode !== 'local') {
      return this.request<ManagedSkillLifecycle>(
        `/api/v1/skills/import?${params.toString()}`,
        {
          method: 'POST',
          body: input,
        },
      );
    }
    if (this.config.projectId) params.set('project_id', this.config.projectId);
    const resourceId = managedSkillPackageResourceId(input.skill_md_content, this.createError);
    const scope = input.scope ?? 'tenant';
    const projectId =
      scope === 'project' ? requireValue(this.config.projectId, 'project id') : null;
    const candidates = (await this.listManagedSkills()).filter(
      (skill) =>
        skill.id === resourceId &&
        skill.scope === scope &&
        (scope === 'tenant' || skill.project_id === projectId),
    );
    if (candidates.length > 1) {
      throw this.createError(
        'Managed skill id is ambiguous in the requested scope',
        422,
        { code: 'managed_skill_scope_ambiguous', resource_id: resourceId, scope },
      );
    }
    const existing = candidates[0];
    if (existing && !input.overwrite) {
      throw this.createError('Managed skill already exists', 409, {
        code: 'managed_resource_already_exists',
        resource_id: resourceId,
        scope,
      });
    }
    const expectedRevision = existing
      ? requireManagedResourceRevision(existing, this.createError)
      : 0;
    const localValue = {
      ...input,
      full_content: input.skill_md_content,
    };
    return this.request<ManagedSkillLifecycle>(`/api/v1/skills/import?${params.toString()}`, {
      method: 'POST',
      body: this.mutationBody(localValue, expectedRevision, resourceId),
    });
  }

  async importManagedSkillZip(
    archive: File,
    input: ManagedSkillZipImportInput = {},
  ): Promise<ManagedSkillLifecycle> {
    const params = this.managedSkillTenantParams();
    const formData = new FormData();
    formData.append('archive', archive);
    formData.append('scope', input.scope ?? 'tenant');
    formData.append('overwrite', String(input.overwrite ?? false));
    if (input.project_id) formData.append('project_id', input.project_id);
    if (input.change_summary) formData.append('change_summary', input.change_summary);
    return this.request<ManagedSkillLifecycle>(
      `/api/v1/skills/import/zip?${params.toString()}`,
      { method: 'POST', body: formData },
    );
  }

  async listManagedSkillVersions(
    skillId: string,
    signal?: AbortSignal,
  ): Promise<ManagedSkillVersionList> {
    const params = this.managedSkillTenantParams();
    params.set('limit', '50');
    return this.request<ManagedSkillVersionList>(
      `/api/v1/skills/${encodeURIComponent(skillId)}/versions?${params.toString()}`,
      { signal },
    );
  }

  async rollbackManagedSkill(
    skillId: string,
    versionNumber: number,
    expectedRevision?: number,
  ): Promise<ManagedSkill> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkill>(
      `/api/v1/skills/${encodeURIComponent(skillId)}/rollback?${params.toString()}`,
      {
        method: 'POST',
        body:
          this.config.mode === 'local'
            ? this.mutationBody(null, expectedRevision, undefined, versionNumber)
            : { version_number: versionNumber },
      },
    );
  }

  async exportManagedSkillPackage(skillId: string): Promise<ManagedSkillPackage> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkillPackage>(
      `/api/v1/skills/${encodeURIComponent(skillId)}/export?${params.toString()}`,
    );
  }

  async getManagedSkillVersion(
    skillId: string,
    versionNumber: number,
  ): Promise<ManagedSkillVersionDetail> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkillVersionDetail>(
      `/api/v1/skills/${encodeURIComponent(skillId)}/versions/${versionNumber}?${params.toString()}`,
    );
  }

  async getManagedSkillEvolution(skillId: string): Promise<ManagedSkillEvolutionDetail> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkillEvolutionDetail>(
      `/api/v1/skills/${encodeURIComponent(skillId)}/evolution?${params.toString()}`,
    );
  }

  async runManagedSkillEvolution(skillId: string): Promise<ManagedSkillEvolutionRun> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkillEvolutionRun>(
      `/api/v1/skills/${encodeURIComponent(skillId)}/evolution/run?${params.toString()}`,
      { method: 'POST' },
    );
  }

  async applyManagedSkillEvolutionJob(jobId: string): Promise<ManagedSkillEvolutionJob> {
    return this.mutateManagedSkillEvolutionJob(jobId, 'apply');
  }

  async rejectManagedSkillEvolutionJob(jobId: string): Promise<ManagedSkillEvolutionJob> {
    return this.mutateManagedSkillEvolutionJob(jobId, 'reject');
  }

  async listManagedAgents(signal?: AbortSignal): Promise<ManagedAgentDefinition[]> {
    const params = new URLSearchParams({ limit: '100', enabled_only: 'false' });
    if (this.config.projectId) params.set('project_id', this.config.projectId);
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    const payload = await this.request<unknown>(
      `/api/v1/agent/definitions?${params.toString()}`,
      { signal },
    );
    return readArray<ManagedAgentDefinition>(
      payload,
      ['definitions', 'items', 'data'],
      'agent_definitions',
      this.createError,
    );
  }

  async listManagedExternalAcpAgents(signal?: AbortSignal): Promise<ManagedExternalAcpAgent[]> {
    const tenantId = requireValue(this.config.tenantId, 'tenant id');
    const payload = await this.request<unknown>(
      `/api/v1/acp/tenants/${encodeURIComponent(tenantId)}/external-agents`,
      { signal },
    );
    return readArray<ManagedExternalAcpAgent>(
      payload,
      ['agents', 'items', 'externalAgents', 'data'],
      'external_acp_agents',
      this.createError,
    );
  }

  async listPromptTemplates(
    tenantId: string,
    signal?: AbortSignal,
  ): Promise<PromptTemplateRecord[]> {
    const requiredTenantId = requireValue(tenantId, 'tenant id');
    const params = new URLSearchParams({
      tenant_id: requiredTenantId,
      limit: '100',
      offset: '0',
    });
    const payload = await this.request<unknown>(
      `/api/v1/agent/templates?${params.toString()}`,
      { signal },
    );
    return this.requirePromptTemplateCatalog(payload, requiredTenantId);
  }

  async createPromptTemplate(
    tenantId: string,
    input: PromptTemplateCreateInput,
    signal?: AbortSignal,
  ): Promise<PromptTemplateRecord> {
    const requiredTenantId = requireValue(tenantId, 'tenant id');
    const request = {
      title: requireValue(input.title, 'template title'),
      content: requireValue(input.content, 'template content'),
      category: requireValue(input.category, 'template category'),
    };
    const params = new URLSearchParams({ tenant_id: requiredTenantId });
    const payload = await this.request<unknown>(
      `/api/v1/agent/templates?${params.toString()}`,
      {
        method: 'POST',
        body: this.mutationBody(request, 0, crypto.randomUUID()),
        signal,
      },
    );
    const template = normalizePromptTemplate(payload, requiredTenantId);
    if (
      !template ||
      template.is_system ||
      template.project_id !== null ||
      template.title !== request.title ||
      template.content !== request.content ||
      template.category !== request.category ||
      template.variables.length !== 0
    ) {
      throw this.createError('Invalid prompt template response', 502, payload);
    }
    return template;
  }

  async deletePromptTemplate(
    templateId: string,
    signal?: AbortSignal,
    expectedRevision?: number,
  ): Promise<void> {
    await this.request<unknown>(
      `/api/v1/agent/templates/${encodeURIComponent(requireValue(templateId, 'template id'))}`,
      {
        method: 'DELETE',
        body: this.mutationBody(null, expectedRevision),
        signal,
      },
    );
  }

  async setManagedAgentEnabled(
    definitionId: string,
    enabled: boolean,
    expectedRevision?: number,
  ): Promise<ManagedAgentDefinition> {
    const params = new URLSearchParams();
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    if (this.config.projectId) params.set('project_id', this.config.projectId);
    const query = params.toString();
    return this.request<ManagedAgentDefinition>(
      `/api/v1/agent/definitions/${encodeURIComponent(definitionId)}/enabled${
        query ? `?${query}` : ''
      }`,
      {
        method: 'PATCH',
        body: this.mutationBody({ enabled }, expectedRevision),
      },
    );
  }

  async createManagedAgentDefinition(
    body: ManagedAgentDefinitionMutation,
  ): Promise<ManagedAgentDefinition> {
    const params = new URLSearchParams();
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    const query = params.toString();
    return this.request<ManagedAgentDefinition>(
      `/api/v1/agent/definitions${query ? `?${query}` : ''}`,
      { method: 'POST', body: this.mutationBody(body, 0, crypto.randomUUID()) },
    );
  }

  async updateManagedAgentDefinition(
    definitionId: string,
    body: ManagedAgentDefinitionMutation,
    expectedRevision?: number,
  ): Promise<ManagedAgentDefinition> {
    const params = new URLSearchParams();
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    const query = params.toString();
    return this.request<ManagedAgentDefinition>(
      `/api/v1/agent/definitions/${encodeURIComponent(definitionId)}${
        query ? `?${query}` : ''
      }`,
      { method: 'PUT', body: this.mutationBody(body, expectedRevision) },
    );
  }

  async deleteManagedAgentDefinition(
    definitionId: string,
    expectedRevision?: number,
  ): Promise<{ deleted: boolean; id: string }> {
    const params = new URLSearchParams();
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    const query = params.toString();
    return this.request<{ deleted: boolean; id: string }>(
      `/api/v1/agent/definitions/${encodeURIComponent(definitionId)}${
        query ? `?${query}` : ''
      }`,
      { method: 'DELETE', body: this.mutationBody(null, expectedRevision) },
    );
  }

  async listManagedSubAgents(signal?: AbortSignal): Promise<ManagedSubAgent[]> {
    const params = new URLSearchParams({ limit: '100', include_filesystem: 'true' });
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    const payload = await this.request<unknown>(`/api/v1/subagents/?${params.toString()}`, {
      signal,
    });
    return readArray<ManagedSubAgent>(
      payload,
      ['subagents', 'items', 'data'],
      'subagents',
      this.createError,
    );
  }

  async setManagedSubAgentEnabled(
    subagentId: string,
    enabled: boolean,
    expectedRevision?: number,
  ): Promise<ManagedSubAgent> {
    const params = new URLSearchParams({ enabled: String(enabled) });
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    return this.request<ManagedSubAgent>(
      `/api/v1/subagents/${encodeURIComponent(subagentId)}/enable?${params.toString()}`,
      {
        method: 'PATCH',
        body:
          this.config.mode === 'local'
            ? this.mutationBody({ enabled }, expectedRevision)
            : undefined,
      },
    );
  }

  async listManagedSubAgentTemplates(
    signal?: AbortSignal,
  ): Promise<ManagedSubAgentTemplateList> {
    const params = new URLSearchParams({ limit: '100' });
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    return this.request<ManagedSubAgentTemplateList>(
      `/api/v1/subagents/templates/list?${params.toString()}`,
      { signal },
    );
  }

  async installManagedSubAgentTemplate(templateId: string): Promise<ManagedSubAgent> {
    const params = new URLSearchParams();
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    return this.request<ManagedSubAgent>(
      `/api/v1/subagents/templates/${encodeURIComponent(templateId)}/install?${params.toString()}`,
      { method: 'POST' },
    );
  }

  async importManagedFilesystemSubAgent(
    name: string,
    projectId?: string,
  ): Promise<ManagedSubAgent> {
    const params = new URLSearchParams();
    if (projectId) params.set('project_id', projectId);
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    return this.request<ManagedSubAgent>(
      `/api/v1/subagents/filesystem/${encodeURIComponent(name)}/import?${params.toString()}`,
      { method: 'POST' },
    );
  }

  async createManagedSubAgent(input: ManagedSubAgentMutation): Promise<ManagedSubAgent> {
    const params = new URLSearchParams();
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    return this.request<ManagedSubAgent>(`/api/v1/subagents/?${params.toString()}`, {
      method: 'POST',
      body: this.mutationBody(input, 0, crypto.randomUUID()),
    });
  }

  async updateManagedSubAgent(
    subagentId: string,
    input: ManagedSubAgentMutation,
    expectedRevision?: number,
  ): Promise<ManagedSubAgent> {
    const params = new URLSearchParams();
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    return this.request<ManagedSubAgent>(
      `/api/v1/subagents/${encodeURIComponent(subagentId)}?${params.toString()}`,
      { method: 'PUT', body: this.mutationBody(input, expectedRevision) },
    );
  }

  async deleteManagedSubAgent(
    subagentId: string,
    expectedRevision?: number,
  ): Promise<void> {
    const params = new URLSearchParams();
    if (this.config.tenantId) params.set('tenant_id', this.config.tenantId);
    await this.request<void>(
      `/api/v1/subagents/${encodeURIComponent(subagentId)}?${params.toString()}`,
      { method: 'DELETE', body: this.mutationBody(null, expectedRevision) },
    );
  }

  private async mutateManagedSkillEvolutionJob(
    jobId: string,
    action: 'apply' | 'reject',
  ): Promise<ManagedSkillEvolutionJob> {
    const params = this.managedSkillTenantParams();
    return this.request<ManagedSkillEvolutionJob>(
      `/api/v1/skills/evolution/jobs/${encodeURIComponent(jobId)}/${action}?${params.toString()}`,
      { method: 'POST' },
    );
  }

  private managedSkillTenantParams(): URLSearchParams {
    return new URLSearchParams({
      tenant_id: requireValue(this.config.tenantId, 'tenant id'),
    });
  }

  private mutationBody(
    value: Record<string, unknown> | null,
    expectedRevision?: number,
    resourceId?: string,
    targetRevision?: number,
  ): Record<string, unknown> | undefined {
    if (this.config.mode !== 'local') return value ?? undefined;
    if (
      expectedRevision === undefined ||
      !Number.isSafeInteger(expectedRevision) ||
      expectedRevision < 0
    ) {
      throw this.createError(
        'Managed resource revision is required for local mutation',
        428,
        { code: 'managed_resource_revision_required' },
      );
    }
    return {
      contract_version: 2,
      expected_revision: expectedRevision,
      idempotency_key: crypto.randomUUID(),
      ...(resourceId ? { resource_id: requireValue(resourceId, 'managed resource id') } : {}),
      value,
      ...(targetRevision === undefined ? {} : { target_revision: targetRevision }),
      vault_refs: [],
    };
  }

  private requirePromptTemplateCatalog(
    payload: unknown,
    tenantId: string,
  ): PromptTemplateRecord[] {
    if (!Array.isArray(payload) || payload.length > 100) {
      throw this.createError('Invalid prompt template catalog response', 502, payload);
    }
    const seenIds = new Set<string>();
    const templates = payload.map((value) => normalizePromptTemplate(value, tenantId));
    if (
      templates.some((template) => template === null) ||
      templates.some((template) => {
        if (template === null || seenIds.has(template.id)) return true;
        seenIds.add(template.id);
        return false;
      })
    ) {
      throw this.createError('Invalid prompt template catalog response', 502, payload);
    }
    return templates as PromptTemplateRecord[];
  }

  private async request<T>(
    path: string,
    options: ManagedResourcesRequestOptions = {},
  ): Promise<T> {
    const headers = new Headers({ Accept: 'application/json' });
    const formDataBody =
      typeof FormData !== 'undefined' && options.body instanceof FormData
        ? options.body
        : null;
    if (options.body !== undefined && !formDataBody) {
      headers.set('Content-Type', 'application/json');
    }
    const credential = this.config.apiKey.trim();
    if (credential) headers.set('Authorization', `Bearer ${credential}`);
    const launchCapability =
      this.config.mode === 'local' ? this.config.localApiToken.trim() : '';
    if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
    const body =
      formDataBody ??
      (options.body === undefined ? undefined : JSON.stringify(options.body));
    const response = await fetch(absoluteUrl(this.config.apiBaseUrl, path), {
      method: options.method ?? 'GET',
      headers,
      body,
      signal: options.signal,
    });
    const contentType = response.headers.get('content-type') ?? '';
    const payload = contentType.includes('application/json')
      ? await response.json().catch(() => null)
      : await response.text().catch(() => '');
    if (!response.ok) {
      const message =
        isRecord(payload) && 'detail' in payload
          ? String(payload.detail)
          : `HTTP ${response.status}`;
      throw this.createError(message, response.status, payload);
    }
    return payload as T;
  }
}

function normalizePromptTemplate(
  value: unknown,
  tenantId: string,
): PromptTemplateRecord | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.id) ||
    value.tenant_id !== tenantId ||
    !(value.project_id === null || typeof value.project_id === 'string') ||
    !isNonEmptyString(value.created_by) ||
    !isNonEmptyString(value.title) ||
    typeof value.content !== 'string' ||
    !isNonEmptyString(value.category) ||
    !Array.isArray(value.variables) ||
    typeof value.is_system !== 'boolean' ||
    !isUnsignedSafeInteger(value.usage_count) ||
    !isNonEmptyString(value.created_at) ||
    !isNonEmptyString(value.updated_at)
  ) {
    return null;
  }
  const variables = value.variables.map(normalizePromptTemplateVariable);
  if (variables.some((variable) => variable === null)) return null;
  return {
    id: value.id,
    tenant_id: value.tenant_id,
    project_id: value.project_id,
    created_by: value.created_by,
    title: value.title,
    content: value.content,
    category: value.category,
    variables: variables as PromptTemplateVariable[],
    is_system: value.is_system,
    usage_count: value.usage_count,
    created_at: value.created_at,
    updated_at: value.updated_at,
    ...(isUnsignedSafeInteger(value.revision) ? { revision: value.revision } : {}),
  };
}

function normalizePromptTemplateVariable(value: unknown): PromptTemplateVariable | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.name) ||
    typeof value.description !== 'string' ||
    typeof value.default_value !== 'string' ||
    typeof value.required !== 'boolean'
  ) {
    return null;
  }
  return {
    name: value.name,
    description: value.description,
    default_value: value.default_value,
    required: value.required,
  };
}

function readArray<T>(
  payload: unknown,
  keys: string[],
  collection: string,
  createError: ManagedResourcesErrorFactory,
): T[] {
  if (Array.isArray(payload)) return payload as T[];
  if (isRecord(payload)) {
    for (const key of keys) {
      if (!Object.prototype.hasOwnProperty.call(payload, key)) continue;
      const value = payload[key];
      if (Array.isArray(value)) return value as T[];
      break;
    }
  }
  throw createError('Managed resource list contract is invalid', 502, {
    code: 'managed_resource_list_contract_invalid',
    collection,
  });
}

function managedSkillPackageResourceId(
  content: string,
  createError: ManagedResourcesErrorFactory,
): string {
  const lines = content.split(/\r?\n/);
  const closingIndex = lines.slice(1).findIndex((line) => line === '---');
  if (lines[0] !== '---' || closingIndex < 0) {
    throw createError('Managed skill package frontmatter is invalid', 422, {
      code: 'invalid_skill_package',
    });
  }
  let frontmatter: unknown;
  try {
    const document = parseDocument(lines.slice(1, closingIndex + 1).join('\n'), {
      customTags: [],
      logLevel: 'silent',
      merge: false,
      prettyErrors: false,
      resolveKnownTags: false,
      schema: 'core',
      strict: true,
      stringKeys: true,
      uniqueKeys: true,
      version: '1.2',
    });
    if (document.errors.length > 0 || document.warnings.length > 0) {
      throw new Error('invalid frontmatter');
    }
    frontmatter = document.toJS({ maxAliasCount: 0 });
  } catch {
    throw createError('Managed skill package frontmatter is invalid', 422, {
      code: 'invalid_skill_package',
    });
  }
  const resourceId =
    isRecord(frontmatter) && isNonEmptyString(frontmatter.name)
      ? frontmatter.name.trim()
      : '';
  const resourceIdBytes = new TextEncoder().encode(resourceId).length;
  if (
    !resourceId ||
    resourceIdBytes > 200 ||
    resourceId.includes('/') ||
    resourceId.includes('\\') ||
    resourceId === '.' ||
    resourceId === '..'
  ) {
    throw createError('Managed skill package name is not a valid resource id', 422, {
      code: 'invalid_managed_resource_id',
    });
  }
  return resourceId;
}

function requireManagedResourceRevision(
  resource: ManagedSkill,
  createError: ManagedResourcesErrorFactory,
): number {
  if (!isUnsignedSafeInteger(resource.revision)) {
    throw createError('Managed resource revision is required for local mutation', 428, {
      code: 'managed_resource_revision_required',
      resource_id: resource.id,
    });
  }
  return resource.revision;
}

function requireValue(value: string, label: string): string {
  const trimmed = value.trim();
  if (!trimmed) throw new Error(`Missing ${label}`);
  return trimmed;
}

function absoluteUrl(baseUrl: string, path: string): string {
  const base = baseUrl.trim().replace(/\/+$/, '');
  return `${base}${path.startsWith('/') ? path : `/${path}`}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isUnsignedSafeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}
