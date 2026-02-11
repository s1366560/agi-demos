/**
 * TrendingEntities - Clickable entity chips showing trending knowledge
 */

import { useEffect, useState, memo } from 'react';

import { useTranslation } from 'react-i18next';

import { TrendingUp } from 'lucide-react';

import { projectStatsService, type TrendingEntity } from '@/services/projectStatsService';

interface TrendingEntitiesProps {
  projectId: string;
  onEntityClick?: (entityName: string) => void;
}

export const TrendingEntities = memo<TrendingEntitiesProps>(({ projectId, onEntityClick }) => {
  const { t } = useTranslation();
  const [entities, setEntities] = useState<TrendingEntity[]>([]);

  useEffect(() => {
    let cancelled = false;
    projectStatsService
      .getTrending(projectId, 8)
      .then((data) => {
        if (!cancelled) setEntities(data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (entities.length === 0) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">
        <TrendingUp size={12} />
        <span>{t('agent.projectContext.trending', 'Trending')}</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {entities.map((entity) => (
          <button
            key={entity.name}
            type="button"
            onClick={() => onEntityClick?.(`Tell me about ${entity.name}`)}
            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded-full
              bg-slate-100 dark:bg-slate-700/60 text-slate-700 dark:text-slate-300
              hover:bg-primary/10 hover:text-primary dark:hover:bg-primary/20
              border border-transparent hover:border-primary/20
              transition-colors cursor-pointer"
            title={entity.summary || entity.name}
          >
            <span className="font-medium">{entity.name}</span>
            <span className="text-[10px] text-slate-400">{entity.mention_count}</span>
          </button>
        ))}
      </div>
    </div>
  );
});
TrendingEntities.displayName = 'TrendingEntities';
