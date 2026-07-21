import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';

import { SkillEvolution } from '@/pages/tenant/SkillEvolution';
import { useTenantStore } from '@/stores/tenant';

import { fireEvent, render, screen, waitFor } from '../../utils';

import type { SkillEvolutionConfigResponse, SkillEvolutionOverviewResponse } from '@/types/agent';
import type { Tenant } from '@/types/memory';

const skillApiMocks = vi.hoisted(() => ({
  getEvolutionOverview: vi.fn(),
  getEvolutionConfig: vi.fn(),
  runEvolutionOverview: vi.fn(),
  updateEvolutionConfig: vi.fn(),
  applyEvolutionJob: vi.fn(),
  rejectEvolutionJob: vi.fn(),
}));
const lazyMessageMocks = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
}));

vi.mock('@/services/skillService', () => ({
  skillAPI: skillApiMocks,
}));

vi.mock('@/components/ui/lazyAntd', () => ({
  LazyEmpty: ({ description }: { description?: string }) => <div>{description}</div>,
  LazyPopconfirm: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  LazySpin: () => <div>Loading</div>,
  useLazyMessage: () => lazyMessageMocks,
}));

const config: SkillEvolutionConfigResponse = {
  enabled: true,
  min_sessions_per_skill: 3,
  scoring_min_sessions_per_skill: 2,
  min_avg_score: 0.75,
  max_sessions_per_batch: 20,
  evolution_interval_minutes: 30,
  publish_mode: 'review',
  auto_apply: false,
};

const overview: SkillEvolutionOverviewResponse = {
  stats: {
    total_sessions: 4,
    skill_sessions: 4,
    no_skill_sessions: 0,
    unprocessed_sessions: 0,
    processed_sessions: 4,
    scored_sessions: 4,
    successful_sessions: 3,
    avg_score: 0.82,
    total_jobs: 0,
    pending_jobs: 0,
    applied_jobs: 0,
    skipped_jobs: 0,
    rejected_jobs: 0,
  },
  monitor: {
    refresh_interval_seconds: 60,
    latest_session_at: '2026-06-16T00:00:00Z',
    latest_job_at: null,
    backlog_count: 0,
    unscored_count: 0,
    blocked_by_review_count: 0,
    eligible_skill_count: 2,
    needs_attention: false,
  },
  stages: [],
  skills: [
    {
      skill_id: 'skill-tenant',
      project_id: null,
      skill_name: 'alpha-skill',
      session_count: 2,
      success_count: 2,
      unprocessed_count: 0,
      scored_count: 2,
      avg_score: 0.9,
      latest_session_at: '2026-06-16T00:00:00Z',
      job_count: 0,
      pending_job_count: 0,
      latest_job_at: null,
    },
    {
      skill_id: 'skill-project',
      project_id: 'project-1',
      skill_name: 'alpha-skill',
      session_count: 2,
      success_count: 1,
      unprocessed_count: 0,
      scored_count: 2,
      avg_score: 0.8,
      latest_session_at: '2026-06-16T00:00:00Z',
      job_count: 0,
      pending_job_count: 0,
      latest_job_at: null,
    },
    {
      skill_id: null,
      project_id: 'project-2',
      skill_name: 'orphan-skill',
      session_count: 1,
      success_count: 1,
      unprocessed_count: 0,
      scored_count: 1,
      avg_score: 0.7,
      latest_session_at: '2026-06-16T00:00:00Z',
      job_count: 0,
      pending_job_count: 0,
      latest_job_at: null,
    },
  ],
  recent_sessions: [],
  recent_jobs: [],
  trigger: {
    capture_hook: 'after_turn_complete',
    capture_timing: 'Captured after each turn.',
    scheduled_timing: 'Every 30 minutes.',
    manual_trigger: '/api/v1/skills/{skill_id}/evolution/run',
    min_sessions_per_skill: 3,
    scoring_min_sessions_per_skill: 2,
    min_avg_score: 0.75,
    max_sessions_per_batch: 20,
    publish_mode: 'review',
    auto_apply: false,
    enabled: true,
  },
};

function makeTenant(overrides: Partial<Tenant> = {}): Tenant {
  return {
    id: 'tenant-1',
    name: 'Acme',
    owner_id: 'admin-1',
    plan: 'enterprise',
    max_projects: 100,
    max_users: 100,
    max_storage: 1000,
    created_at: '2026-06-15T00:00:00Z',
    ...overrides,
  };
}

function renderSkillEvolution(route = '/tenant/acme/evolution') {
  return render(
    <Routes>
      <Route path="/tenant/:tenantId/evolution" element={<SkillEvolution />} />
    </Routes>,
    { route }
  );
}

describe('SkillEvolution', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTenantStore.setState({ currentTenant: makeTenant() });
    skillApiMocks.getEvolutionOverview.mockResolvedValue(overview);
    skillApiMocks.getEvolutionConfig.mockResolvedValue(config);
  });

  it('keeps same-name tenant and project skill summaries distinct', async () => {
    renderSkillEvolution();

    await waitFor(() => {
      expect(screen.getAllByRole('link', { name: 'alpha-skill' })).toHaveLength(2);
    });
    expect(skillApiMocks.getEvolutionOverview).toHaveBeenCalledWith({
      job_limit: 25,
      session_limit: 25,
      skill_limit: 100,
      tenant_id: 'acme',
    });
    expect(skillApiMocks.getEvolutionConfig).toHaveBeenCalledWith({ tenant_id: 'acme' });

    const links = screen.getAllByRole('link', { name: 'alpha-skill' });
    expect(links[0]).toHaveAttribute('href', '/tenant/acme/skills/skill-tenant');
    expect(links[1]).toHaveAttribute('href', '/tenant/acme/skills/skill-project');
    expect(screen.getByText('Tenant scope')).toBeInTheDocument();
    expect(screen.getByText('Project project-1')).toBeInTheDocument();
    expect(screen.getByText('Project project-2')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'orphan-skill' })).not.toBeInTheDocument();
  });

  it('shows a retryable error instead of an empty state when loading fails', async () => {
    skillApiMocks.getEvolutionOverview.mockRejectedValueOnce(new Error('network'));
    renderSkillEvolution();

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Failed to load skill evolution data');
    });

    const retryButton = screen.getByRole('button', { name: /Retry/ });
    fireEvent.click(retryButton);

    await waitFor(() => {
      expect(screen.getAllByRole('link', { name: 'alpha-skill' })).toHaveLength(2);
    });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows an empty state when no skill evidence is captured', async () => {
    skillApiMocks.getEvolutionOverview.mockResolvedValueOnce({
      ...overview,
      skills: [
        {
          skill_id: null,
          project_id: null,
          skill_name: '__no_skill__',
          session_count: 4,
          success_count: 3,
          unprocessed_count: 0,
          scored_count: 4,
          avg_score: 0.82,
          latest_session_at: '2026-06-16T00:00:00Z',
          job_count: 0,
          pending_job_count: 0,
          latest_job_at: null,
        },
      ],
    });
    renderSkillEvolution();

    await waitFor(() => {
      expect(screen.getByText('No skill evidence has been captured yet')).toBeInTheDocument();
    });

    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('shows scope on recent sessions and jobs', async () => {
    skillApiMocks.getEvolutionOverview.mockResolvedValueOnce({
      ...overview,
      recent_sessions: [
        {
          id: 'session-1',
          skill_name: 'session-skill',
          conversation_id: 'conversation-1',
          project_id: 'project-session',
          user_query: 'Summarize account risk',
          summary: null,
          judge_scores: null,
          overall_score: 0.81,
          success: true,
          execution_time_ms: 1234,
          tool_call_count: 2,
          processed: true,
          created_at: '2026-06-16T00:00:00Z',
        },
      ],
      recent_jobs: [
        {
          id: 'job-1',
          project_id: 'project-job',
          skill_name: 'job-skill',
          action: 'improve_skill',
          status: 'pending_review',
          rationale: 'Better instructions',
          candidate_preview: null,
          candidate_content: null,
          blocked_by_review: true,
          session_ids: ['session-1'],
          skill_version_id: null,
          created_at: '2026-06-16T00:00:00Z',
          applied_at: null,
        },
      ],
    });
    renderSkillEvolution();

    await waitFor(() => {
      expect(screen.getAllByRole('link', { name: 'alpha-skill' })).toHaveLength(2);
    });

    fireEvent.click(screen.getByRole('tab', { name: /tenant\.skillEvolution\.tabs\.sessions/ }));
    await waitFor(() => {
      expect(screen.getByText('Project project-session')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('tab', { name: /tenant\.skillEvolution\.tabs\.jobs/ }));
    await waitFor(() => {
      expect(screen.getByText('Project project-job')).toBeInTheDocument();
    });
  });
});
