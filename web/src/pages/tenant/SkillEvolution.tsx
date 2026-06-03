import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FC, ReactNode } from 'react';
import type { TFunction } from 'i18next';

import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router-dom';

import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Clock3,
  GitBranch,
  History,
  RefreshCw,
  Scale,
  TimerReset,
} from 'lucide-react';

import { LazyEmpty, LazySpin, useLazyMessage } from '@/components/ui/lazyAntd';
import { skillAPI } from '@/services/skillService';

import type {
  SkillEvolutionJobResponse,
  SkillEvolutionOverviewResponse,
  SkillEvolutionSessionResponse,
  SkillEvolutionSkillSummaryResponse,
} from '@/types/agent';

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
  const width = `${Math.max(0, Math.min(100, value))}%`;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-[oklch(0.92_0.004_255)] dark:bg-[oklch(0.28_0.006_255)]">
      <div className="h-full rounded-full bg-[oklch(0.53_0.16_255)]" style={{ width }} />
    </div>
  );
}

function SkillRow({ summary }: { summary: SkillEvolutionSkillSummaryResponse }) {
  const successRate = summary.session_count
    ? Math.round((summary.success_count / summary.session_count) * 100)
    : 0;

  return (
    <tr className="border-b border-[oklch(0.9_0.006_255)] last:border-b-0 dark:border-[oklch(0.28_0.006_255)]">
      <td className="max-w-[220px] px-4 py-3 align-top">
        <div className={`min-w-0 truncate text-sm font-semibold ${pageText}`}>
          {summary.skill_name}
        </div>
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
        <div className="flex flex-wrap gap-1.5">
          <StatusPill>{summary.job_count}</StatusPill>
          {summary.pending_job_count > 0 ? (
            <StatusPill tone="pending">{summary.pending_job_count}</StatusPill>
          ) : null}
        </div>
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

function RecentJobRow({ job }: { job: SkillEvolutionJobResponse }) {
  const { t } = useTranslation();
  const tone =
    job.status === 'applied' ? 'success' : job.status === 'pending_review' ? 'pending' : 'neutral';

  return (
    <div className="border-b border-[oklch(0.9_0.006_255)] px-4 py-3 last:border-b-0 dark:border-[oklch(0.28_0.006_255)]">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`text-sm font-semibold ${pageText}`}>{job.skill_name}</span>
        <StatusPill>{translateEnum(t, 'tenant.skillEvolution.jobActions', job.action)}</StatusPill>
        <StatusPill tone={tone}>
          {translateEnum(t, 'tenant.skillEvolution.jobStatuses', job.status)}
        </StatusPill>
      </div>
      {job.rationale ? (
        <div className={`mt-2 line-clamp-3 text-sm ${mutedText}`}>{job.rationale}</div>
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

  const loadOverview = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await skillAPI.getEvolutionOverview({
        job_limit: 25,
        session_limit: 25,
        skill_limit: 100,
      });
      setOverview(data);
    } catch {
      message?.error(t('tenant.skillEvolution.loadFailed'));
    } finally {
      setIsLoading(false);
    }
  }, [message, t]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

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
  const processingRate = stats.total_sessions
    ? Math.round((stats.processed_sessions / stats.total_sessions) * 100)
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
          <button type="button" onClick={() => void loadOverview()} className={actionButton}>
            <RefreshCw size={15} />
            {t('common.refresh')}
          </button>
        </header>

        <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <StatCard
            icon={<Activity size={17} />}
            label={t('tenant.skillEvolution.stats.captured')}
            value={formatNumber(stats.total_sessions)}
            detail={t('tenant.skillEvolution.stats.skillCaptured', {
              count: stats.skill_sessions,
            })}
          />
          <StatCard
            icon={<TimerReset size={17} />}
            label={t('tenant.skillEvolution.stats.processing')}
            value={`${processingRate}%`}
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
                  {t('tenant.skillEvolution.units.sessions', {
                    count: trigger.min_sessions_per_skill,
                  })}
                </StatusPill>
              </div>
            </div>
          </div>
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
                    onClick={() => setActivePanel(tab.id)}
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
                  <table className="w-full min-w-[760px] text-left">
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
                      </tr>
                    </thead>
                    <tbody>
                      {overview.skills.map((summary) => (
                        <SkillRow key={summary.skill_name} summary={summary} />
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
                  overview.recent_jobs.map((job) => <RecentJobRow key={job.id} job={job} />)
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
