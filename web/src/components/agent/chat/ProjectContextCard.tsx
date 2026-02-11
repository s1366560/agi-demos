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

  useEffect(() => {
    let cancelled = false;
    projectStatsService
      .getStats(projectId)
      .then((data) => {
        if (!cancelled) setStats(data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (!stats) return null;

  const items = [
    {
      icon: <MessageSquare size={16} className="text-blue-500" />,
      label: t('agent.projectContext.conversations', 'Conversations'),
      value: stats.conversation_count,
    },
    {
      icon: <Brain size={16} className="text-purple-500" />,
      label: t('agent.projectContext.memories', 'Memories'),
      value: stats.memory_count,
    },
    {
      icon: <Activity size={16} className="text-emerald-500" />,
      label: t('agent.projectContext.entities', 'Entities'),
      value: stats.node_count,
    },
    {
      icon: <Users size={16} className="text-amber-500" />,
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
            <div className="text-sm font-semibold text-slate-800 dark:text-slate-200">
              {item.value.toLocaleString()}
            </div>
            <div className="text-[10px] text-slate-500 dark:text-slate-400">{item.label}</div>
          </div>
        </div>
      ))}
    </div>
  );
});
ProjectContextCard.displayName = 'ProjectContextCard';
