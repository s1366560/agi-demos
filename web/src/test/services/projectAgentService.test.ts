import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/services/client/httpClient', () => ({
  httpClient: {
    get: vi.fn(),
  },
}));

import { httpClient } from '@/services/client/httpClient';
import { ProjectAgentContractError, projectAgentService } from '@/services/projectAgentService';

describe('projectAgentService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('loads project-scoped recent runs through the trace authority', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: 'project/1',
      runs: [],
      total: 0,
    });

    await projectAgentService.listRuns('project/1', { status: 'running,completed', limit: 25 });

    expect(httpClient.get).toHaveBeenCalledWith('/agent/trace/runs/project/project%2F1', {
      params: { status: 'running,completed', limit: 25 },
    });
  });

  it('loads the project-scoped active run count', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: 'project-1',
      active_count: 2,
    });

    const response = await projectAgentService.getActiveRunCount('project-1');

    expect(httpClient.get).toHaveBeenCalledWith('/agent/trace/runs/project/project-1/active/count');
    expect(response.active_count).toBe(2);
  });

  it('fails closed when trace authority returns another project scope', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: 'other-project',
      runs: [],
      total: 0,
    });

    await expect(projectAgentService.listRuns('project-1')).rejects.toMatchObject<
      Partial<ProjectAgentContractError>
    >({ reasonCode: 'project_agent_trace_scope_conflict' });
  });

  it('fails closed on malformed active counts', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: 'project-1',
      active_count: -1,
    });

    await expect(projectAgentService.getActiveRunCount('project-1')).rejects.toMatchObject<
      Partial<ProjectAgentContractError>
    >({ reasonCode: 'project_agent_trace_contract_invalid' });
  });

  it('fails closed when active-count authority returns another project scope', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: 'other-project',
      active_count: 1,
    });

    await expect(projectAgentService.getActiveRunCount('project-1')).rejects.toMatchObject<
      Partial<ProjectAgentContractError>
    >({ reasonCode: 'project_agent_trace_scope_conflict' });
  });

  it('loads a project-authorized tenant-shared patterns projection', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: 'project-1',
      tenant_id: 'tenant-1',
      scope_kind: 'tenant_shared',
      patterns: [],
      total: 0,
      page: 1,
      page_size: 50,
    });

    const response = await projectAgentService.listSharedPatterns('project-1');

    expect(httpClient.get).toHaveBeenCalledWith('/agent/workflows/patterns/project/project-1', {
      params: { page: 1, page_size: 50 },
    });
    expect(response.scope_kind).toBe('tenant_shared');
  });

  it('decodes the bounded workflow pattern and step contract', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: 'project-1',
      tenant_id: 'tenant-1',
      scope_kind: 'tenant_shared',
      patterns: [
        {
          id: 'pattern-1',
          tenant_id: 'tenant-1',
          name: 'Pattern',
          description: 'Description',
          steps: [
            {
              step_number: 1,
              description: 'Search',
              tool_name: 'web_search',
              expected_output_format: 'json',
              similarity_threshold: 0.8,
              tool_parameters: null,
            },
          ],
          success_rate: 0.912,
          usage_count: 1,
          created_at: '2026-08-05T00:00:00Z',
          updated_at: '2026-08-05T00:00:00Z',
          metadata: null,
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    });

    const response = await projectAgentService.listSharedPatterns('project-1');

    expect(response.patterns[0]).toMatchObject({
      id: 'pattern-1',
      tenant_id: 'tenant-1',
      success_rate: 0.912,
      metadata: undefined,
      steps: [{ step_number: 1, similarity_threshold: 0.8, tool_parameters: undefined }],
    });
  });

  it('rejects tenant-shared patterns containing a cross-tenant item', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: 'project-1',
      tenant_id: 'tenant-1',
      scope_kind: 'tenant_shared',
      patterns: [
        {
          id: 'pattern-1',
          tenant_id: 'other-tenant',
          name: 'Pattern',
          description: 'Description',
          steps: [],
          success_rate: 0.9,
          usage_count: 1,
          created_at: '2026-08-05T00:00:00Z',
          updated_at: '2026-08-05T00:00:00Z',
          metadata: {},
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    });

    await expect(projectAgentService.listSharedPatterns('project-1')).rejects.toMatchObject<
      Partial<ProjectAgentContractError>
    >({ reasonCode: 'project_agent_patterns_contract_invalid' });
  });

  it('rejects patterns whose success rate is outside the domain contract', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: 'project-1',
      tenant_id: 'tenant-1',
      scope_kind: 'tenant_shared',
      patterns: [
        {
          id: 'pattern-1',
          tenant_id: 'tenant-1',
          name: 'Pattern',
          description: 'Description',
          steps: [],
          success_rate: 1.1,
          usage_count: 1,
          created_at: '2026-08-05T00:00:00Z',
          updated_at: '2026-08-05T00:00:00Z',
          metadata: {},
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    });

    await expect(projectAgentService.listSharedPatterns('project-1')).rejects.toMatchObject<
      Partial<ProjectAgentContractError>
    >({ reasonCode: 'project_agent_patterns_contract_invalid' });
  });

  it('rejects malformed workflow steps before presentation', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: 'project-1',
      tenant_id: 'tenant-1',
      scope_kind: 'tenant_shared',
      patterns: [
        {
          id: 'pattern-1',
          tenant_id: 'tenant-1',
          name: 'Pattern',
          description: 'Description',
          steps: [
            {
              step_number: 0,
              description: 'Search',
              tool_name: 'web_search',
              expected_output_format: 'json',
              similarity_threshold: 1.1,
              tool_parameters: {},
            },
          ],
          success_rate: 0.9,
          usage_count: 1,
          created_at: '2026-08-05T00:00:00Z',
          updated_at: '2026-08-05T00:00:00Z',
          metadata: {},
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    });

    await expect(projectAgentService.listSharedPatterns('project-1')).rejects.toMatchObject<
      Partial<ProjectAgentContractError>
    >({ reasonCode: 'project_agent_patterns_contract_invalid' });
  });

  it('fails closed when patterns authority returns another project scope', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: 'other-project',
      tenant_id: 'tenant-1',
      scope_kind: 'tenant_shared',
      patterns: [],
      total: 0,
      page: 1,
      page_size: 50,
    });

    await expect(projectAgentService.listSharedPatterns('project-1')).rejects.toMatchObject<
      Partial<ProjectAgentContractError>
    >({ reasonCode: 'project_agent_patterns_scope_conflict' });
  });

  it.each([
    { tenant_id: '', scope_kind: 'tenant_shared' },
    { tenant_id: 'tenant-1', scope_kind: 'project_owned' },
  ])('fails closed on invalid patterns ownership metadata %#', async (ownership) => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: 'project-1',
      ...ownership,
      patterns: [],
      total: 0,
      page: 1,
      page_size: 50,
    });

    await expect(projectAgentService.listSharedPatterns('project-1')).rejects.toMatchObject<
      Partial<ProjectAgentContractError>
    >({ reasonCode: 'project_agent_patterns_contract_invalid' });
  });
});
