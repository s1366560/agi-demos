import { httpClient } from './client/httpClient';

import type {
  ProjectActiveRunCountDTO,
  ProjectSubAgentRunListDTO,
  SubAgentRunDTO,
} from '../types/multiAgent';
import type { WorkflowPattern } from '../types/agent';

const BASE_URL = '/agent/trace/runs/project';

export interface ProjectRunListOptions {
  status?: string | undefined;
  limit?: number | undefined;
}

export interface ProjectSharedPatternsResponse {
  project_id: string;
  tenant_id: string;
  scope_kind: 'tenant_shared';
  patterns: WorkflowPattern[];
  total: number;
  page: number;
  page_size: number;
}

export interface ProjectSharedPatternOptions {
  page?: number | undefined;
  pageSize?: number | undefined;
  minSuccessRate?: number | undefined;
}

export class ProjectAgentContractError extends Error {
  constructor(public readonly reasonCode: string) {
    super(reasonCode);
    this.name = 'ProjectAgentContractError';
  }
}

export const projectAgentService = {
  async listRuns(
    projectId: string,
    options: ProjectRunListOptions = {}
  ): Promise<ProjectSubAgentRunListDTO> {
    const response = await httpClient.get<unknown>(`${BASE_URL}/${encodeURIComponent(projectId)}`, {
      params: options,
    });
    return decodeRunList(response, projectId, options.limit ?? 20, options.status);
  },

  async getActiveRunCount(projectId: string): Promise<ProjectActiveRunCountDTO> {
    const response = await httpClient.get<unknown>(
      `${BASE_URL}/${encodeURIComponent(projectId)}/active/count`
    );
    return decodeActiveCount(response, projectId);
  },

  async listSharedPatterns(
    projectId: string,
    options: ProjectSharedPatternOptions = {}
  ): Promise<ProjectSharedPatternsResponse> {
    const page = options.page ?? 1;
    const pageSize = options.pageSize ?? 50;
    const params: Record<string, number> = { page, page_size: pageSize };
    if (options.minSuccessRate !== undefined) params.min_success_rate = options.minSuccessRate;
    const response = await httpClient.get<unknown>(
      `/agent/workflows/patterns/project/${encodeURIComponent(projectId)}`,
      { params }
    );
    return decodeSharedPatterns(response, projectId, page, pageSize);
  },
};

const RUN_STATUSES = new Set([
  'pending',
  'running',
  'completed',
  'failed',
  'cancelled',
  'timed_out',
]);

function decodeRunList(
  value: unknown,
  projectId: string,
  limit: number,
  statusFilter?: string
): ProjectSubAgentRunListDTO {
  if (!isRecord(value) || value.project_id !== projectId) {
    throw contractError('project_agent_trace_scope_conflict');
  }
  if (
    !Array.isArray(value.runs) ||
    value.runs.length > Math.min(Math.max(limit, 1), 100) ||
    !nonNegativeInteger(value.total) ||
    value.total !== value.runs.length
  ) {
    throw contractError('project_agent_trace_contract_invalid');
  }
  const statuses = statusFilter ? new Set(statusFilter.split(',').filter(Boolean)) : null;
  const runs = value.runs.map((run) => decodeRun(run, statuses));
  return { project_id: projectId, runs, total: value.total };
}

function decodeRun(value: unknown, expectedStatuses: Set<string> | null): SubAgentRunDTO {
  if (
    !isRecord(value) ||
    !identifier(value.run_id) ||
    !identifier(value.conversation_id) ||
    !identifier(value.subagent_name) ||
    typeof value.task !== 'string' ||
    !RUN_STATUSES.has(String(value.status)) ||
    (expectedStatuses && !expectedStatuses.has(String(value.status))) ||
    typeof value.created_at !== 'string' ||
    !nullableString(value.started_at) ||
    !nullableString(value.ended_at) ||
    !nullableString(value.summary) ||
    !nullableString(value.error) ||
    !nullableNumber(value.execution_time_ms) ||
    !nullableNumber(value.tokens_used) ||
    !isRecord(value.metadata) ||
    Object.keys(value.metadata).length !== 0 ||
    value.frozen_result_text !== null ||
    !nullableString(value.frozen_at) ||
    !nullableString(value.trace_id) ||
    !nullableString(value.parent_span_id)
  ) {
    throw contractError('project_agent_trace_contract_invalid');
  }
  return value as unknown as SubAgentRunDTO;
}

function decodeActiveCount(value: unknown, projectId: string): ProjectActiveRunCountDTO {
  if (!isRecord(value) || value.project_id !== projectId) {
    throw contractError('project_agent_trace_scope_conflict');
  }
  if (!nonNegativeInteger(value.active_count)) {
    throw contractError('project_agent_trace_contract_invalid');
  }
  return { project_id: projectId, active_count: value.active_count };
}

function decodeSharedPatterns(
  value: unknown,
  projectId: string,
  page: number,
  pageSize: number
): ProjectSharedPatternsResponse {
  if (!isRecord(value) || value.project_id !== projectId) {
    throw contractError('project_agent_patterns_scope_conflict');
  }
  const tenantId = value.tenant_id;
  if (
    !identifier(tenantId) ||
    value.scope_kind !== 'tenant_shared' ||
    value.page !== page ||
    value.page_size !== pageSize ||
    !Array.isArray(value.patterns) ||
    value.patterns.length > Math.min(Math.max(pageSize, 1), 100) ||
    !nonNegativeInteger(value.total) ||
    value.total < value.patterns.length
  ) {
    throw contractError('project_agent_patterns_contract_invalid');
  }
  const patterns = value.patterns.map((pattern) => decodePattern(pattern, tenantId));
  return {
    project_id: projectId,
    tenant_id: tenantId,
    scope_kind: 'tenant_shared',
    patterns,
    total: value.total,
    page,
    page_size: pageSize,
  };
}

function decodePattern(value: unknown, tenantId: string): WorkflowPattern {
  if (
    !isRecord(value) ||
    !identifier(value.id) ||
    value.tenant_id !== tenantId ||
    !nonEmptyString(value.name) ||
    !nonEmptyString(value.description) ||
    !Array.isArray(value.steps) ||
    !finiteInRange(value.success_rate, 0, 1) ||
    !nonNegativeInteger(value.usage_count) ||
    typeof value.created_at !== 'string' ||
    typeof value.updated_at !== 'string' ||
    (value.metadata !== null && value.metadata !== undefined && !isRecord(value.metadata))
  ) {
    throw contractError('project_agent_patterns_contract_invalid');
  }
  const steps = value.steps.map(decodePatternStep);
  return {
    id: value.id,
    tenant_id: tenantId,
    name: value.name,
    description: value.description,
    steps,
    success_rate: value.success_rate,
    usage_count: value.usage_count,
    created_at: value.created_at,
    updated_at: value.updated_at,
    metadata: isRecord(value.metadata) ? value.metadata : undefined,
  };
}

function decodePatternStep(value: unknown): WorkflowPattern['steps'][number] {
  if (
    !isRecord(value) ||
    !Number.isInteger(value.step_number) ||
    Number(value.step_number) < 1 ||
    !nonEmptyString(value.description) ||
    !nonEmptyString(value.tool_name) ||
    typeof value.expected_output_format !== 'string' ||
    !finiteInRange(value.similarity_threshold, 0, 1) ||
    (value.tool_parameters !== null &&
      value.tool_parameters !== undefined &&
      !isRecord(value.tool_parameters))
  ) {
    throw contractError('project_agent_patterns_contract_invalid');
  }
  return {
    step_number: value.step_number as number,
    description: value.description,
    tool_name: value.tool_name,
    expected_output_format: value.expected_output_format,
    similarity_threshold: value.similarity_threshold,
    tool_parameters: isRecord(value.tool_parameters) ? value.tool_parameters : undefined,
  };
}

function contractError(reasonCode: string): ProjectAgentContractError {
  return new ProjectAgentContractError(reasonCode);
}

function identifier(value: unknown): value is string {
  return typeof value === 'string' && value.trim() === value && value.length > 0;
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function nullableString(value: unknown): boolean {
  return value === null || typeof value === 'string';
}

function nullableNumber(value: unknown): boolean {
  return value === null || (typeof value === 'number' && Number.isFinite(value));
}

function nonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

function finiteInRange(value: unknown, minimum: number, maximum: number): value is number {
  return (
    typeof value === 'number' && Number.isFinite(value) && value >= minimum && value <= maximum
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

export default projectAgentService;
