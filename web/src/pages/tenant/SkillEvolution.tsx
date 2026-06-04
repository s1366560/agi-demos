import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FC, ReactNode } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useLocation, useNavigate } from 'react-router-dom';

import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock3,
  GitBranch,
  History,
  PauseCircle,
  PlayCircle,
  RefreshCw,
  Scale,
  TimerReset,
  XCircle,
} from 'lucide-react';

import { skillAPI } from '@/services/skillService';

import { LazyEmpty, LazySpin, useLazyMessage } from '@/components/ui/lazyAntd';

import type {
  SkillEvolutionConfigResponse,
  SkillEvolutionJobResponse,
  SkillEvolutionMonitorResponse,
  SkillEvolutionOverviewResponse,
  SkillEvolutionSessionResponse,
  SkillEvolutionStageResponse,
  SkillEvolutionSkillSummaryResponse,
} from '@/types/agent';

import type { TFunction } from 'i18next';

const pageText = 'text-[oklch(0.24_0.01_255)] dark:text-[oklch(0.94_0.006_255)]';
const mutedText = 'text-[oklch(0.48_0.01_255)] dark:text-[oklch(0.68_0.008_255)]';
const surface =
  'border border-[oklch(0.9_0.006_255)] bg-[oklch(0.99_0.004_255)] dark:border-[oklch(0.28_0.006_255)] dark:bg-[oklch(0.18_0.006_255)]';
const actionButton =
  'inline-flex h-9 items-center justify-center gap-2 rounded-[4px] border border-[oklch(0.86_0.006_255)] px-3 text-sm font-medium text-[oklch(0.34_0.01_255)] transition-colors hover:bg-[oklch(0.95_0.005_255)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] dark:border-[oklch(0.34_0.006_255)] dark:text-[oklch(0.82_0.006_255)] dark:hover:bg-[oklch(0.24_0.006_255)]';
type EvolutionPanelTab = 'skills' | 'sessions' | 'jobs';

function formatNumber(value: number): string {
  return new Intl.NumberFormat().format(value);
}

function formatScore(value: number | null): string {
  return value === null ? '-' : value.toFixed(2);
}

function formatDate(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : '-';
}

function translateEnum(t: TFunction, prefix: string, value: string) {
  return t(`${prefix}.${value}`, value);
}

function policyNumberValue(value: string, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function getStageStatusText(t: TFunction, stage: SkillEvolutionStageResponse): string {
  if (stage.status === 'waiting') {
    return t(
      `tenant.skillEvolution.stageWaitingStatuses.${stage.id}`,
      t('tenant.skillEvolution.stageStatuses.waiting')
    );
  }
  return translateEnum(t, 'tenant.skillEvolution.stageStatuses', stage.status);
}

function getStageCountsText(t: TFunction, stage: SkillEvolutionStageResponse): string {
  return t(`tenant.skillEvolution.stageCountDetails.${stage.id}`, {
    count: stage.count,
    backlog: stage.backlog_count,
    defaultValue: t('tenant.skillEvolution.monitor.stageCounts', {
      count: stage.count,
      backlog: stage.backlog_count,
    }),
  });
}

function StatusPill({ children, tone = 'neutral' }: { children: ReactNode; tone?: string }) {
  const toneClass =
    tone === 'success'
      ? 'border-[oklch(0.78_0.08_155)] bg-[oklch(0.96_0.035_155)] text-[oklch(0.38_0.11_155)] dark:border-[oklch(0.44_0.08_155)] dark:bg-[oklch(0.24_0.04_155)] dark:text-[oklch(0.76_0.09_155)]'
      : tone === 'pending'
        ? 'border-[oklch(0.84_0.08_80)] bg-[oklch(0.98_0.035_80)] text-[oklch(0.48_0.1_80)] dark:border-[oklch(0.44_0.07_80)] dark:bg-[oklch(0.25_0.04_80)] dark:text-[oklch(0.8_0.09_80)]'
        : 'border-[oklch(0.86_0.006_255)] bg-[oklch(0.97_0.004_255)] text-[oklch(0.42_0.008_255)] dark:border-[oklch(0.34_0.006_255)] dark:bg-[oklch(0.22_0.006_255)] dark:text-[oklch(0.76_0.006_255)]';

  return (
    <span
      className={`inline-flex h-6 items-center rounded-full border px-2 text-[11px] font-medium ${toneClass}`}
    >
      {children}
    </span>
  );
}

function StatCard({
  icon,
  label,
  value,
  detail,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className={`rounded-[6px] p-4 ${surface}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className={`text-[11px] font-medium uppercase tracking-normal ${mutedText}`}>
            {label}
          </div>
          <div className={`mt-2 text-2xl font-semibold leading-none tracking-normal ${pageText}`}>
            {value}
          </div>
        </div>
        <div className="flex h-8 w-8 items-center justify-center rounded-[4px] bg-[oklch(0.95_0.005_255)] text-[oklch(0.42_0.01_255)] dark:bg-[oklch(0.24_0.006_255)] dark:text-[oklch(0.76_0.006_255)]">
          {icon}
        </div>
      </div>
      <div className={`mt-3 text-xs ${mutedText}`}>{detail}</div>
    </div>
  );
}

function ProgressMeter({ value }: { value: number }) {
  const width = `${String(Math.max(0, Math.min(100, value)))}%`;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-[oklch(0.92_0.004_255)] dark:bg-[oklch(0.28_0.006_255)]">
      <div className="h-full rounded-full bg-[oklch(0.53_0.16_255)]" style={{ width }} />
    </div>
  );
}

function StageRail({ stages }: { stages: SkillEvolutionStageResponse[] }) {
  const { t } = useTranslation();

  return (
    <div className={`rounded-[6px] p-4 ${surface}`}>
      <div className="flex flex-col gap-3 lg:flex-row lg:items-stretch">
        {stages.map((stage, index) => {
          const isBlocked = stage.status === 'blocked';
          const isComplete = stage.status === 'complete';
          const markerClass = isBlocked
            ? 'border-[oklch(0.72_0.13_35)] bg-[oklch(0.97_0.045_35)] text-[oklch(0.48_0.14_35)] dark:border-[oklch(0.48_0.12_35)] dark:bg-[oklch(0.25_0.05_35)] dark:text-[oklch(0.82_0.11_35)]'
            : isComplete
              ? 'border-[oklch(0.78_0.08_155)] bg-[oklch(0.96_0.035_155)] text-[oklch(0.38_0.11_155)] dark:border-[oklch(0.44_0.08_155)] dark:bg-[oklch(0.24_0.04_155)] dark:text-[oklch(0.76_0.09_155)]'
              : 'border-[oklch(0.84_0.08_80)] bg-[oklch(0.98_0.035_80)] text-[oklch(0.48_0.1_80)] dark:border-[oklch(0.44_0.07_80)] dark:bg-[oklch(0.25_0.04_80)] dark:text-[oklch(0.8_0.09_80)]';

          return (
            <div key={stage.id} className="flex min-w-0 flex-1 items-stretch gap-3">
              <div className="flex min-w-0 flex-1 gap-3 rounded-[6px] border border-[oklch(0.9_0.006_255)] bg-[oklch(0.98_0.003_255)] p-3 dark:border-[oklch(0.28_0.006_255)] dark:bg-[oklch(0.16_0.006_255)]">
                <div
                  className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-[4px] border ${markerClass}`}
                >
                  {isBlocked ? (
                    <AlertTriangle size={15} />
                  ) : isComplete ? (
                    <CheckCircle2 size={15} />
                  ) : (
                    <TimerReset size={15} />
                  )}
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`text-sm font-semibold ${pageText}`}>
                      {translateEnum(t, 'tenant.skillEvolution.stages', stage.id)}
                    </span>
                    <StatusPill tone={isBlocked ? 'pending' : isComplete ? 'success' : 'neutral'}>
                      {getStageStatusText(t, stage)}
                    </StatusPill>
                  </div>
                  <div className={`mt-1 text-xs ${mutedText}`}>{getStageCountsText(t, stage)}</div>
                  <div className={`mt-1 text-xs leading-5 ${mutedText}`}>
                    {translateEnum(t, 'tenant.skillEvolution.stageDetails', stage.id)}
                  </div>
                </div>
              </div>
              {index < stages.length - 1 ? (
                <div className={`hidden items-center text-xs ${mutedText} lg:flex`}>
                  <ArrowRight size={15} />
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function buildFallbackMonitor(
  overview: SkillEvolutionOverviewResponse
): SkillEvolutionMonitorResponse {
  const { stats } = overview;
  const scorableBacklogCount = overview.skills
    .filter(
      (skill) =>
        skill.skill_name !== '__no_skill__' &&
        skill.session_count >= overview.trigger.scoring_min_sessions_per_skill
    )
    .reduce((total, skill) => total + skill.unprocessed_count, 0);
  return {
    refresh_interval_seconds: 15,
    latest_session_at: overview.recent_sessions[0]?.created_at ?? null,
    latest_job_at: overview.recent_jobs[0]?.created_at ?? null,
    backlog_count: scorableBacklogCount,
    unscored_count: Math.max(stats.processed_sessions - stats.scored_sessions, 0),
    blocked_by_review_count: stats.pending_jobs,
    eligible_skill_count: overview.skills.filter(
      (skill) =>
        skill.skill_name !== '__no_skill__' &&
        skill.session_count >= overview.trigger.min_sessions_per_skill &&
        skill.avg_score !== null &&
        skill.avg_score >= overview.trigger.min_avg_score
    ).length,
    needs_attention:
      scorableBacklogCount > 0 ||
      Math.max(stats.processed_sessions - stats.scored_sessions, 0) > 0 ||
      stats.pending_jobs > 0,
  };
}

function buildFallbackStages(
  overview: SkillEvolutionOverviewResponse,
  monitor: SkillEvolutionMonitorResponse
): SkillEvolutionStageResponse[] {
  const { stats } = overview;
  return [
    {
      id: 'capture',
      label: 'capture',
      status: stats.total_sessions ? 'active' : 'waiting',
      count: stats.total_sessions,
      backlog_count: 0,
      detail: '',
    },
    {
      id: 'summarize',
      label: 'summarize',
      status: monitor.backlog_count ? 'waiting' : 'complete',
      count: stats.processed_sessions,
      backlog_count: monitor.backlog_count,
      detail: '',
    },
    {
      id: 'judge',
      label: 'judge',
      status: monitor.unscored_count ? 'waiting' : 'complete',
      count: stats.scored_sessions,
      backlog_count: monitor.unscored_count,
      detail: '',
    },
    {
      id: 'review',
      label: 'review',
      status: stats.pending_jobs ? 'blocked' : 'complete',
      count: stats.pending_jobs,
      backlog_count: stats.pending_jobs,
      detail: '',
    },
    {
      id: 'apply',
      label: 'apply',
      status: stats.applied_jobs ? 'active' : 'waiting',
      count: stats.applied_jobs,
      backlog_count: 0,
      detail: '',
    },
  ];
}

function SkillRow({
  summary,
  minSessions,
  minAvgScore,
  tenantBasePath,
}: {
  summary: SkillEvolutionSkillSummaryResponse;
  minSessions: number;
  minAvgScore: number;
  tenantBasePath: string;
}) {
  const { t } = useTranslation();
  const skillDetailId = summary.skill_id ?? encodeURIComponent(summary.skill_name);
  const successRate = summary.session_count
    ? Math.round((summary.success_count / summary.session_count) * 100)
    : 0;
  const evolutionStatus =
    summary.pending_job_count > 0
      ? {
          tone: 'pending' as const,
          label: t('tenant.skillEvolution.eligibility.pendingReview'),
        }
      : summary.job_count > 0
        ? {
            tone: 'success' as const,
            label: t('tenant.skillEvolution.eligibility.hasJob'),
          }
        : summary.session_count < minSessions
          ? {
              tone: 'neutral' as const,
              label: t('tenant.skillEvolution.eligibility.notEnoughSessions', {
                count: minSessions,
              }),
            }
          : summary.avg_score === null
            ? {
                tone: 'pending' as const,
                label: t('tenant.skillEvolution.eligibility.notScored'),
              }
            : summary.avg_score < minAvgScore
              ? {
                  tone: 'neutral' as const,
                  label: t('tenant.skillEvolution.eligibility.lowScore', {
                    score: formatScore(summary.avg_score),
                    threshold: formatScore(minAvgScore),
                  }),
                }
              : {
                  tone: 'success' as const,
                  label: t('tenant.skillEvolution.eligibility.eligible'),
                };

  return (
    <tr className="border-b border-[oklch(0.9_0.006_255)] last:border-b-0 dark:border-[oklch(0.28_0.006_255)]">
      <td className="max-w-[220px] px-4 py-3 align-top">
        <Link
          to={`${tenantBasePath}/skills/${skillDetailId}`}
          className={`block min-w-0 truncate text-sm font-semibold text-[oklch(0.42_0.15_255)] underline-offset-4 hover:text-[oklch(0.35_0.18_255)] hover:underline dark:text-[oklch(0.76_0.12_255)] dark:hover:text-[oklch(0.84_0.13_255)]`}
        >
          {summary.skill_name}
        </Link>
        <div className={`mt-1 text-xs ${mutedText}`}>{formatDate(summary.latest_session_at)}</div>
      </td>
      <td className={`px-4 py-3 text-sm ${pageText}`}>{formatNumber(summary.session_count)}</td>
      <td className="px-4 py-3">
        <div className={`mb-1 text-xs ${mutedText}`}>{successRate}%</div>
        <ProgressMeter value={successRate} />
      </td>
      <td className={`px-4 py-3 text-sm ${pageText}`}>{formatScore(summary.avg_score)}</td>
      <td className={`px-4 py-3 text-sm ${pageText}`}>{formatNumber(summary.unprocessed_count)}</td>
      <td className="px-4 py-3">
        <div className="flex min-w-[140px] flex-wrap gap-1.5">
          <StatusPill>{summary.job_count}</StatusPill>
          {summary.pending_job_count > 0 ? (
            <StatusPill tone="pending">{summary.pending_job_count}</StatusPill>
          ) : null}
        </div>
      </td>
      <td className="px-4 py-3">
        <StatusPill tone={evolutionStatus.tone}>{evolutionStatus.label}</StatusPill>
      </td>
    </tr>
  );
}

function RecentSessionRow({ session }: { session: SkillEvolutionSessionResponse }) {
  const { t } = useTranslation();

  return (
    <div className="border-b border-[oklch(0.9_0.006_255)] px-4 py-3 last:border-b-0 dark:border-[oklch(0.28_0.006_255)]">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`text-sm font-semibold ${pageText}`}>{session.skill_name}</span>
        <StatusPill tone={session.success ? 'success' : 'neutral'}>
          {t(
            session.success
              ? 'tenant.skillEvolution.status.success'
              : 'tenant.skillEvolution.status.failed'
          )}
        </StatusPill>
        <StatusPill tone={session.processed ? 'success' : 'pending'}>
          {t(
            session.processed
              ? 'tenant.skillEvolution.status.processed'
              : 'tenant.skillEvolution.status.queued'
          )}
        </StatusPill>
      </div>
      <div className={`mt-2 line-clamp-2 text-sm ${mutedText}`}>
        {session.user_query || session.summary || session.conversation_id}
      </div>
      <div className={`mt-2 flex flex-wrap gap-3 text-xs ${mutedText}`}>
        <span>{formatDate(session.created_at)}</span>
        <span>{formatScore(session.overall_score)}</span>
        <span>
          {t('tenant.skillEvolution.units.tools', {
            count: session.tool_call_count,
          })}
        </span>
        <span>
          {t('tenant.skillEvolution.units.ms', {
            count: session.execution_time_ms,
          })}
        </span>
      </div>
    </div>
  );
}

function RecentJobRow({
  job,
  isProcessing,
  onApply,
  onReject,
}: {
  job: SkillEvolutionJobResponse;
  isProcessing: boolean;
  onApply: (jobId: string) => void;
  onReject: (jobId: string) => void;
}) {
  const { t } = useTranslation();
  const tone =
    job.status === 'applied' ? 'success' : job.status === 'pending_review' ? 'pending' : 'neutral';
  const actionable = job.status === 'pending_review';

  return (
    <div className="border-b border-[oklch(0.9_0.006_255)] px-4 py-3 last:border-b-0 dark:border-[oklch(0.28_0.006_255)]">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`text-sm font-semibold ${pageText}`}>{job.skill_name}</span>
            <StatusPill>
              {translateEnum(t, 'tenant.skillEvolution.jobActions', job.action)}
            </StatusPill>
            <StatusPill tone={tone}>
              {translateEnum(t, 'tenant.skillEvolution.jobStatuses', job.status)}
            </StatusPill>
          </div>
        </div>
        {actionable ? (
          <div className="flex shrink-0 gap-2">
            <button
              type="button"
              onClick={() => {
                onApply(job.id);
              }}
              disabled={isProcessing}
              className={actionButton}
            >
              <CheckCircle2 size={14} />
              {t('tenant.skillEvolution.jobs.apply')}
            </button>
            <button
              type="button"
              onClick={() => {
                onReject(job.id);
              }}
              disabled={isProcessing}
              className={actionButton}
            >
              <XCircle size={14} />
              {t('tenant.skillEvolution.jobs.reject')}
            </button>
          </div>
        ) : null}
      </div>
      {job.rationale ? (
        <div className={`mt-2 line-clamp-3 text-sm ${mutedText}`}>{job.rationale}</div>
      ) : null}
      {job.candidate_preview ? (
        <pre className="mt-2 max-h-36 overflow-auto rounded-[4px] border border-[oklch(0.88_0.006_255)] bg-[oklch(0.96_0.004_255)] p-3 text-xs leading-5 text-[oklch(0.28_0.01_255)] dark:border-[oklch(0.3_0.006_255)] dark:bg-[oklch(0.14_0.006_255)] dark:text-[oklch(0.84_0.006_255)]">
          {job.candidate_preview}
        </pre>
      ) : null}
      <div className={`mt-2 text-xs ${mutedText}`}>
        {formatDate(job.created_at)} ·{' '}
        {t('tenant.skillEvolution.units.sessions', {
          count: job.session_ids.length,
        })}
      </div>
    </div>
  );
}

export const SkillEvolution: FC = () => {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const message = useLazyMessage();
  const [overview, setOverview] = useState<SkillEvolutionOverviewResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [activePanel, setActivePanel] = useState<EvolutionPanelTab>('skills');
  const [processingJobId, setProcessingJobId] = useState<string | null>(null);
  const [isManualRunLoading, setIsManualRunLoading] = useState(false);
  const [isPolicySaving, setIsPolicySaving] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);
  const [policyDraft, setPolicyDraft] = useState<SkillEvolutionConfigResponse | null>(null);

  const loadOverview = useCallback(async () => {
    setIsLoading(true);
    try {
      const [data, config] = await Promise.all([
        skillAPI.getEvolutionOverview({
          job_limit: 25,
          session_limit: 25,
          skill_limit: 100,
        }),
        skillAPI.getEvolutionConfig(),
      ]);
      setOverview(data);
      setPolicyDraft(config);
      setLastUpdatedAt(new Date());
    } catch {
      message?.error(t('tenant.skillEvolution.loadFailed'));
    } finally {
      setIsLoading(false);
    }
  }, [message, t]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  useEffect(() => {
    if (!autoRefresh || !overview) {
      return undefined;
    }
    const monitor = overview.monitor ?? buildFallbackMonitor(overview);
    const refreshMs = Math.max(monitor.refresh_interval_seconds, 5) * 1000;
    const intervalId = window.setInterval(() => {
      void loadOverview();
    }, refreshMs);
    return () => {
      window.clearInterval(intervalId);
    };
  }, [autoRefresh, loadOverview, overview]);

  const handleManualRun = useCallback(async () => {
    setIsManualRunLoading(true);
    try {
      await skillAPI.runEvolutionOverview();
      message?.success(t('tenant.skillEvolution.manualRun.success'));
      await loadOverview();
    } catch {
      message?.error(t('tenant.skillEvolution.manualRun.failed'));
    } finally {
      setIsManualRunLoading(false);
    }
  }, [loadOverview, message, t]);

  const handlePolicySave = useCallback(async () => {
    if (!policyDraft) {
      return;
    }
    setIsPolicySaving(true);
    try {
      const saved = await skillAPI.updateEvolutionConfig(policyDraft);
      setPolicyDraft(saved);
      message?.success(t('tenant.skillEvolution.policy.saveSuccess'));
      await loadOverview();
    } catch {
      message?.error(t('tenant.skillEvolution.policy.saveFailed'));
    } finally {
      setIsPolicySaving(false);
    }
  }, [loadOverview, message, policyDraft, t]);

  const updatePolicyDraft = useCallback((patch: Partial<SkillEvolutionConfigResponse>) => {
    setPolicyDraft((current) => (current ? { ...current, ...patch } : current));
  }, []);

  const handleApplyJob = useCallback(
    async (jobId: string) => {
      setProcessingJobId(jobId);
      try {
        await skillAPI.applyEvolutionJob(jobId);
        message?.success(t('tenant.skillEvolution.jobs.applySuccess'));
        await loadOverview();
      } catch {
        message?.error(t('tenant.skillEvolution.jobs.applyFailed'));
      } finally {
        setProcessingJobId(null);
      }
    },
    [loadOverview, message, t]
  );

  const handleRejectJob = useCallback(
    async (jobId: string) => {
      setProcessingJobId(jobId);
      try {
        await skillAPI.rejectEvolutionJob(jobId);
        message?.success(t('tenant.skillEvolution.jobs.rejectSuccess'));
        await loadOverview();
      } catch {
        message?.error(t('tenant.skillEvolution.jobs.rejectFailed'));
      } finally {
        setProcessingJobId(null);
      }
    },
    [loadOverview, message, t]
  );

  const activeSkills = useMemo(
    () => overview?.skills.filter((skill) => skill.skill_name !== '__no_skill__') ?? [],
    [overview?.skills]
  );
  const panelTabs = useMemo(
    () =>
      overview
        ? [
            {
              id: 'skills' as const,
              label: t('tenant.skillEvolution.tabs.skills'),
              count: activeSkills.length,
            },
            {
              id: 'sessions' as const,
              label: t('tenant.skillEvolution.tabs.sessions'),
              count: overview.recent_sessions.length,
            },
            {
              id: 'jobs' as const,
              label: t('tenant.skillEvolution.tabs.jobs'),
              count: overview.recent_jobs.length,
            },
          ]
        : [],
    [activeSkills.length, overview, t]
  );
  const tenantBasePath = useMemo(() => {
    const segments = location.pathname.split('/').filter(Boolean);
    const tenantIndex = segments.indexOf('tenant');
    const tenantId = tenantIndex >= 0 ? segments[tenantIndex + 1] : undefined;
    return tenantId ? `/tenant/${tenantId}` : '/tenant';
  }, [location.pathname]);

  if (isLoading && !overview) {
    return (
      <div className="flex h-full items-center justify-center">
        <LazySpin size="large" />
      </div>
    );
  }

  if (!overview) {
    return (
      <div className="flex h-full items-center justify-center">
        <LazyEmpty description={t('tenant.skillEvolution.empty')} />
      </div>
    );
  }

  const { stats, trigger } = overview;
  const monitor = overview.monitor ?? buildFallbackMonitor(overview);
  const stages = overview.stages ?? buildFallbackStages(overview, monitor);
  const processingRate = stats.skill_sessions
    ? Math.round((stats.processed_sessions / stats.skill_sessions) * 100)
    : 0;
  const attributionRate = stats.total_sessions
    ? Math.round((stats.skill_sessions / stats.total_sessions) * 100)
    : 0;

  return (
    <div className="min-h-full bg-[oklch(0.985_0.003_255)] px-4 py-6 dark:bg-[oklch(0.13_0.006_255)] sm:px-6 lg:px-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <header className="flex flex-col gap-4 border-b border-[oklch(0.88_0.006_255)] pb-5 dark:border-[oklch(0.28_0.006_255)] lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className={`text-xs font-medium uppercase tracking-normal ${mutedText}`}>
              {t('tenant.skillEvolution.eyebrow')}
            </div>
            <h1 className={`mt-2 text-3xl font-semibold tracking-normal ${pageText}`}>
              {t('tenant.skillEvolution.title')}
            </h1>
            <p className={`mt-2 max-w-3xl text-sm leading-6 ${mutedText}`}>
              {t('tenant.skillEvolution.subtitle')}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => {
                setAutoRefresh((current) => !current);
              }}
              className={actionButton}
            >
              {autoRefresh ? <PauseCircle size={15} /> : <PlayCircle size={15} />}
              {t(
                autoRefresh
                  ? 'tenant.skillEvolution.monitor.pause'
                  : 'tenant.skillEvolution.monitor.resume'
              )}
            </button>
            <button
              type="button"
              onClick={() => void handleManualRun()}
              disabled={isManualRunLoading || !trigger.enabled}
              className={`${actionButton} disabled:cursor-not-allowed disabled:opacity-60`}
            >
              <PlayCircle size={15} />
              {isManualRunLoading
                ? t('tenant.skillEvolution.manualRun.running')
                : t('tenant.skillEvolution.manualRun.action')}
            </button>
            <button type="button" onClick={() => void loadOverview()} className={actionButton}>
              <RefreshCw size={15} />
              {t('common.refresh')}
            </button>
          </div>
        </header>

        <section
          className={`rounded-[6px] border p-4 ${
            monitor.needs_attention
              ? 'border-[oklch(0.82_0.1_70)] bg-[oklch(0.98_0.035_70)] dark:border-[oklch(0.44_0.08_70)] dark:bg-[oklch(0.23_0.035_70)]'
              : surface
          }`}
        >
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex min-w-0 items-start gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[4px] bg-[oklch(0.94_0.018_80)] text-[oklch(0.48_0.1_80)] dark:bg-[oklch(0.26_0.04_80)] dark:text-[oklch(0.82_0.1_80)]">
                {monitor.needs_attention ? <AlertTriangle size={17} /> : <CheckCircle2 size={17} />}
              </div>
              <div className="min-w-0">
                <div className={`text-sm font-semibold ${pageText}`}>
                  {t(
                    monitor.needs_attention
                      ? 'tenant.skillEvolution.monitor.attention'
                      : 'tenant.skillEvolution.monitor.healthy'
                  )}
                </div>
                <div className={`mt-1 text-sm ${mutedText}`}>
                  {t('tenant.skillEvolution.monitor.summary', {
                    backlog: monitor.backlog_count,
                    unscored: monitor.unscored_count,
                    blocked: monitor.blocked_by_review_count,
                    eligible: monitor.eligible_skill_count,
                  })}
                </div>
              </div>
            </div>
            <div className={`flex flex-wrap gap-x-4 gap-y-1 text-xs ${mutedText}`}>
              <span>
                {t('tenant.skillEvolution.monitor.lastUpdated', {
                  time: formatDate(lastUpdatedAt?.toISOString()),
                })}
              </span>
              <span>
                {t('tenant.skillEvolution.monitor.latestSession', {
                  time: formatDate(monitor.latest_session_at),
                })}
              </span>
              <span>
                {t('tenant.skillEvolution.monitor.latestJob', {
                  time: formatDate(monitor.latest_job_at),
                })}
              </span>
            </div>
          </div>
        </section>

        <StageRail stages={stages} />

        <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <StatCard
            icon={<Activity size={17} />}
            label={t('tenant.skillEvolution.stats.captured')}
            value={formatNumber(stats.total_sessions)}
            detail={t('tenant.skillEvolution.stats.skillCaptured', {
              count: stats.skill_sessions,
              rate: attributionRate,
            })}
          />
          <StatCard
            icon={<TimerReset size={17} />}
            label={t('tenant.skillEvolution.stats.processing')}
            value={`${String(processingRate)}%`}
            detail={t('tenant.skillEvolution.stats.queued', {
              count: stats.unprocessed_sessions,
            })}
          />
          <StatCard
            icon={<Scale size={17} />}
            label={t('tenant.skillEvolution.stats.score')}
            value={formatScore(stats.avg_score)}
            detail={t('tenant.skillEvolution.stats.scored', {
              count: stats.scored_sessions,
            })}
          />
          <StatCard
            icon={<GitBranch size={17} />}
            label={t('tenant.skillEvolution.stats.jobs')}
            value={formatNumber(stats.total_jobs)}
            detail={t('tenant.skillEvolution.stats.pending', {
              count: stats.pending_jobs,
              applied: stats.applied_jobs,
              rejected: stats.rejected_jobs ?? 0,
            })}
          />
        </section>

        <section className={`rounded-[6px] p-4 ${surface}`}>
          <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr_1fr]">
            <div>
              <div className={`flex items-center gap-2 text-sm font-semibold ${pageText}`}>
                <Clock3 size={16} />
                {t('tenant.skillEvolution.trigger.capture')}
              </div>
              <p className={`mt-2 text-sm leading-6 ${mutedText}`}>{trigger.capture_timing}</p>
            </div>
            <div>
              <div className={`flex items-center gap-2 text-sm font-semibold ${pageText}`}>
                <History size={16} />
                {t('tenant.skillEvolution.trigger.schedule')}
              </div>
              <p className={`mt-2 text-sm leading-6 ${mutedText}`}>{trigger.scheduled_timing}</p>
            </div>
            <div>
              <div className={`flex items-center gap-2 text-sm font-semibold ${pageText}`}>
                <CheckCircle2 size={16} />
                {t('tenant.skillEvolution.trigger.policy')}
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                <StatusPill>
                  {t(
                    trigger.enabled
                      ? 'tenant.skillEvolution.status.enabled'
                      : 'tenant.skillEvolution.status.disabled'
                  )}
                </StatusPill>
                <StatusPill>
                  {translateEnum(t, 'tenant.skillEvolution.publishModes', trigger.publish_mode)}
                </StatusPill>
                <StatusPill>
                  {t(
                    trigger.auto_apply
                      ? 'tenant.skillEvolution.status.autoApply'
                      : 'tenant.skillEvolution.status.review'
                  )}
                </StatusPill>
                <StatusPill>
                  {t('tenant.skillEvolution.units.scoringSessions', {
                    count: trigger.scoring_min_sessions_per_skill,
                  })}
                </StatusPill>
                <StatusPill>
                  {t('tenant.skillEvolution.units.sessions', {
                    count: trigger.min_sessions_per_skill,
                  })}
                </StatusPill>
                <StatusPill>
                  {t('tenant.skillEvolution.units.minScore', {
                    score: formatScore(trigger.min_avg_score),
                  })}
                </StatusPill>
              </div>
            </div>
          </div>
          {policyDraft ? (
            <div className="mt-4 border-t border-[oklch(0.9_0.006_255)] pt-4 dark:border-[oklch(0.28_0.006_255)]">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <label className="flex min-h-10 items-center gap-2 text-sm font-medium">
                  <input
                    type="checkbox"
                    checked={policyDraft.enabled}
                    onChange={(event) => {
                      updatePolicyDraft({ enabled: event.currentTarget.checked });
                    }}
                    className="h-4 w-4 rounded-[3px]"
                  />
                  <span className={pageText}>{t('tenant.skillEvolution.policy.enabled')}</span>
                </label>
                <label className="flex min-h-10 items-center gap-2 text-sm font-medium">
                  <input
                    type="checkbox"
                    checked={policyDraft.auto_apply}
                    onChange={(event) => {
                      updatePolicyDraft({ auto_apply: event.currentTarget.checked });
                    }}
                    className="h-4 w-4 rounded-[3px]"
                  />
                  <span className={pageText}>{t('tenant.skillEvolution.policy.autoApply')}</span>
                </label>
                <label className="flex flex-col gap-1 text-xs font-medium">
                  <span className={mutedText}>
                    {t('tenant.skillEvolution.policy.publishMode')}
                  </span>
                  <select
                    value={policyDraft.publish_mode}
                    onChange={(event) => {
                      updatePolicyDraft({ publish_mode: event.currentTarget.value });
                    }}
                    className="h-9 rounded-[4px] border border-[oklch(0.86_0.006_255)] bg-transparent px-2 text-sm"
                  >
                    <option value="review">{t('tenant.skillEvolution.policy.reviewMode')}</option>
                    <option value="direct">{t('tenant.skillEvolution.policy.directMode')}</option>
                  </select>
                </label>
                <label className="flex flex-col gap-1 text-xs font-medium">
                  <span className={mutedText}>
                    {t('tenant.skillEvolution.policy.scoringMinSessions')}
                  </span>
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={policyDraft.scoring_min_sessions_per_skill}
                    onChange={(event) => {
                      updatePolicyDraft({
                        scoring_min_sessions_per_skill: Math.max(
                          1,
                          policyNumberValue(
                            event.currentTarget.value,
                            policyDraft.scoring_min_sessions_per_skill
                          )
                        ),
                      });
                    }}
                    className="h-9 rounded-[4px] border border-[oklch(0.86_0.006_255)] bg-transparent px-2 text-sm"
                  />
                </label>
                <label className="flex flex-col gap-1 text-xs font-medium">
                  <span className={mutedText}>
                    {t('tenant.skillEvolution.policy.evolutionMinSessions')}
                  </span>
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={policyDraft.min_sessions_per_skill}
                    onChange={(event) => {
                      updatePolicyDraft({
                        min_sessions_per_skill: Math.max(
                          1,
                          policyNumberValue(
                            event.currentTarget.value,
                            policyDraft.min_sessions_per_skill
                          )
                        ),
                      });
                    }}
                    className="h-9 rounded-[4px] border border-[oklch(0.86_0.006_255)] bg-transparent px-2 text-sm"
                  />
                </label>
                <label className="flex flex-col gap-1 text-xs font-medium">
                  <span className={mutedText}>{t('tenant.skillEvolution.policy.minScore')}</span>
                  <input
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={policyDraft.min_avg_score}
                    onChange={(event) => {
                      updatePolicyDraft({
                        min_avg_score: Math.min(
                          1,
                          Math.max(
                            0,
                            policyNumberValue(event.currentTarget.value, policyDraft.min_avg_score)
                          )
                        ),
                      });
                    }}
                    className="h-9 rounded-[4px] border border-[oklch(0.86_0.006_255)] bg-transparent px-2 text-sm"
                  />
                </label>
                <label className="flex flex-col gap-1 text-xs font-medium">
                  <span className={mutedText}>{t('tenant.skillEvolution.policy.batchSize')}</span>
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={policyDraft.max_sessions_per_batch}
                    onChange={(event) => {
                      updatePolicyDraft({
                        max_sessions_per_batch: Math.max(
                          1,
                          policyNumberValue(
                            event.currentTarget.value,
                            policyDraft.max_sessions_per_batch
                          )
                        ),
                      });
                    }}
                    className="h-9 rounded-[4px] border border-[oklch(0.86_0.006_255)] bg-transparent px-2 text-sm"
                  />
                </label>
                <label className="flex flex-col gap-1 text-xs font-medium">
                  <span className={mutedText}>{t('tenant.skillEvolution.policy.interval')}</span>
                  <input
                    type="number"
                    min={1}
                    max={10080}
                    value={policyDraft.evolution_interval_minutes}
                    onChange={(event) => {
                      updatePolicyDraft({
                        evolution_interval_minutes: Math.max(
                          1,
                          policyNumberValue(
                            event.currentTarget.value,
                            policyDraft.evolution_interval_minutes
                          )
                        ),
                      });
                    }}
                    className="h-9 rounded-[4px] border border-[oklch(0.86_0.006_255)] bg-transparent px-2 text-sm"
                  />
                </label>
              </div>
              <div className="mt-3 flex justify-end">
                <button
                  type="button"
                  onClick={() => void handlePolicySave()}
                  disabled={isPolicySaving}
                  className={`${actionButton} disabled:cursor-not-allowed disabled:opacity-60`}
                >
                  <CheckCircle2 size={15} />
                  {isPolicySaving
                    ? t('tenant.skillEvolution.policy.saving')
                    : t('tenant.skillEvolution.policy.save')}
                </button>
              </div>
            </div>
          ) : null}
        </section>

        <section className={`overflow-hidden rounded-[6px] ${surface}`}>
          <div className="border-b border-[oklch(0.9_0.006_255)] px-3 pt-3 dark:border-[oklch(0.28_0.006_255)]">
            <div
              role="tablist"
              aria-label={t('tenant.skillEvolution.tabs.ariaLabel')}
              className="flex gap-1 overflow-x-auto"
            >
              {panelTabs.map((tab) => {
                const isActive = activePanel === tab.id;
                return (
                  <button
                    key={tab.id}
                    id={`skill-evolution-tab-${tab.id}`}
                    type="button"
                    role="tab"
                    aria-selected={isActive}
                    aria-controls={`skill-evolution-panel-${tab.id}`}
                    onClick={() => {
                      setActivePanel(tab.id);
                    }}
                    className={`inline-flex h-10 shrink-0 items-center gap-2 border-b-2 px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] ${
                      isActive
                        ? 'border-[oklch(0.53_0.16_255)] text-[oklch(0.25_0.04_255)] dark:text-[oklch(0.88_0.05_255)]'
                        : `border-transparent hover:text-[oklch(0.35_0.04_255)] ${mutedText}`
                    }`}
                  >
                    {tab.label}
                    <span className="rounded-full border border-[oklch(0.86_0.006_255)] px-1.5 text-[11px] font-medium dark:border-[oklch(0.34_0.006_255)]">
                      {formatNumber(tab.count)}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          <div
            id={`skill-evolution-panel-${activePanel}`}
            role="tabpanel"
            aria-labelledby={`skill-evolution-tab-${activePanel}`}
          >
            {activePanel === 'skills' ? (
              <>
                <div className="px-4 py-3">
                  <h2 className={`text-sm font-semibold ${pageText}`}>
                    {t('tenant.skillEvolution.skills.title')}
                  </h2>
                  <p className={`mt-1 text-xs ${mutedText}`}>
                    {t('tenant.skillEvolution.skills.subtitle', { count: activeSkills.length })}
                  </p>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[900px] text-left">
                    <thead>
                      <tr className={`border-y border-[oklch(0.9_0.006_255)] text-xs ${mutedText}`}>
                        <th className="px-4 py-3 font-medium">
                          {t('tenant.skillEvolution.table.skill')}
                        </th>
                        <th className="px-4 py-3 font-medium">
                          {t('tenant.skillEvolution.table.sessions')}
                        </th>
                        <th className="px-4 py-3 font-medium">
                          {t('tenant.skillEvolution.table.success')}
                        </th>
                        <th className="px-4 py-3 font-medium">
                          {t('tenant.skillEvolution.table.score')}
                        </th>
                        <th className="px-4 py-3 font-medium">
                          {t('tenant.skillEvolution.table.queued')}
                        </th>
                        <th className="px-4 py-3 font-medium">
                          {t('tenant.skillEvolution.table.jobs')}
                        </th>
                        <th className="px-4 py-3 font-medium">
                          {t('tenant.skillEvolution.table.eligibility')}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {activeSkills.map((summary) => (
                        <SkillRow
                          key={summary.skill_name}
                          summary={summary}
                          minSessions={trigger.min_sessions_per_skill}
                          minAvgScore={trigger.min_avg_score}
                          tenantBasePath={tenantBasePath}
                        />
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : null}

            {activePanel === 'sessions' ? (
              overview.recent_sessions.length > 0 ? (
                overview.recent_sessions.map((session) => (
                  <RecentSessionRow key={session.id} session={session} />
                ))
              ) : (
                <div className="p-6">
                  <LazyEmpty description={t('tenant.skillEvolution.sessions.empty')} />
                </div>
              )
            ) : null}

            {activePanel === 'jobs' ? (
              <>
                <div className="flex justify-end border-b border-[oklch(0.9_0.006_255)] px-4 py-3 dark:border-[oklch(0.28_0.006_255)]">
                  <button
                    type="button"
                    onClick={() => void navigate(`${tenantBasePath}/skills`)}
                    className={`inline-flex items-center gap-1 text-xs font-medium hover:text-[oklch(0.52_0.16_255)] ${mutedText}`}
                  >
                    {t('tenant.skillEvolution.jobs.openSkills')}
                    <ArrowRight size={13} />
                  </button>
                </div>
                {overview.recent_jobs.length > 0 ? (
                  overview.recent_jobs.map((job) => (
                    <RecentJobRow
                      key={job.id}
                      job={job}
                      isProcessing={processingJobId === job.id}
                      onApply={(jobId) => {
                        void handleApplyJob(jobId);
                      }}
                      onReject={(jobId) => {
                        void handleRejectJob(jobId);
                      }}
                    />
                  ))
                ) : (
                  <div className="p-6">
                    <LazyEmpty description={t('tenant.skillEvolution.jobs.empty')} />
                  </div>
                )}
              </>
            ) : null}
          </div>
        </section>
      </div>
    </div>
  );
};

export default SkillEvolution;
