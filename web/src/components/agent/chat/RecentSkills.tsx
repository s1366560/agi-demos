/**
 * RecentSkills - Quick access to recently used skills
 */

import { useEffect, useState, memo } from 'react';

import { useTranslation } from 'react-i18next';

import { Zap, Clock } from 'lucide-react';

import { projectStatsService, type RecentSkill } from '@/services/projectStatsService';

interface RecentSkillsProps {
  projectId: string;
  onSkillClick?: ((skillName: string) => void) | undefined;
}

export const RecentSkills = memo<RecentSkillsProps>(({ projectId, onSkillClick }) => {
  const { t } = useTranslation();
  const [skills, setSkills] = useState<RecentSkill[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setError(null);
    projectStatsService
      .getRecentSkills(projectId)
      .then((data) => {
        if (!cancelled) setSkills(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : 'Failed to load recent skills';
          setError(msg);
          console.error('RecentSkills: fetch failed', err);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (error) {
    return (
      <div className="text-xs text-red-500 dark:text-red-400 px-3 py-2">{error}</div>
    );
  }

  if (skills.length === 0) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">
        <Clock size={12} />
        <span>{t('agent.projectContext.recentSkills', 'Recently Used')}</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {skills.map((skill) => (
          <button
            key={skill.name}
            type="button"
            onClick={() => onSkillClick?.(`/${skill.name} `)}
            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded-full
              bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300
              hover:bg-emerald-100 dark:hover:bg-emerald-900/30
              border border-emerald-200/60 dark:border-emerald-800/40
              transition-colors cursor-pointer"
          >
            <Zap size={10} />
            <span className="font-medium">{skill.name}</span>
          </button>
        ))}
      </div>
    </div>
  );
});
RecentSkills.displayName = 'RecentSkills';
