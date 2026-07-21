/**
 * ProjectContextCard - Shows project statistics in the welcome screen
 */

import { useEffect, useState, memo } from 'react';

import { useTranslation } from 'react-i18next';

import { MessageSquare, Brain, Users, Activity } from 'lucide-react';

import { projectStatsService, type ProjectStats } from '@/services/projectStatsService';

interface ProjectContextCardProps {
  projectId: string;
}

export const ProjectContextCard = memo<ProjectContextCardProps>(({ projectId }) => {
  const { t } = useTranslation();
  const [stats, setStats] = useState<ProjectStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setError(null);
    projectStatsService
      .getStats(projectId)
      .then((data) => {
        if (!cancelled) setStats(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const msg =
            err instanceof Error
              ? err.message
              : t('agent.projectContext.statsLoadFailed', {
                  defaultValue: 'Failed to load project stats',
                });
          setError(msg);
          console.error('ProjectContextCard: fetch failed', err);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, t]);

  if (error) {
    return <div className="text-xs text-red-500 dark:text-red-400 px-3 py-2">{error}</div>;
  }

  if (!stats) {
    return (
      <div
        className="flex items-center gap-4 px-4 py-3 bg-slate-50/80 dark:bg-slate-800/50 rounded-xl border border-slate-200/60 dark:border-slate-700/60"
        aria-hidden="true"
      >
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-2">
            <div className="h-4 w-4 rounded bg-slate-200 dark:bg-slate-700 animate-pulse motion-reduce:animate-none" />
            <div className="space-y-1">
              <div className="h-3.5 w-8 rounded bg-slate-200 dark:bg-slate-700 animate-pulse motion-reduce:animate-none" />
              <div className="h-2.5 w-12 rounded bg-slate-200 dark:bg-slate-700 animate-pulse motion-reduce:animate-none" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  const items = [
    {
      icon: <MessageSquare size={16} className="text-blue-500" />,
      label: t('agent.projectContext.conversations', 'Conversations'),
      value: stats.conversation_count,
    },
    {
      icon: <Brain size={16} className="text-primary" />,
      label: t('agent.projectContext.memories', 'Memories'),
      value: stats.memory_count,
    },
    {
      icon: <Activity size={16} className="text-emerald-500" />,
      label: t('agent.projectContext.entities', 'Entities'),
      value: stats.node_count,
    },
    {
      icon: <Users size={16} className="text-slate-500" />,
      label: t('agent.projectContext.members', 'Members'),
      value: stats.member_count,
    },
  ];

  return (
    <div className="flex items-center gap-4 px-4 py-3 bg-slate-50/80 dark:bg-slate-800/50 rounded-xl border border-slate-200/60 dark:border-slate-700/60">
      {items.map((item) => (
        <div key={item.label} className="flex items-center gap-2">
          {item.icon}
          <div className="text-center">
            <div className="text-sm font-semibold text-slate-800 dark:text-slate-200 tabular-nums">
              {item.value.toLocaleString()}
            </div>
            <div className="text-2xs text-slate-500 dark:text-slate-400">{item.label}</div>
          </div>
        </div>
      ))}
    </div>
  );
});
ProjectContextCard.displayName = 'ProjectContextCard';
