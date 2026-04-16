import React, { useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import { Button, Skeleton } from 'antd';
import { Plus, Target } from 'lucide-react';

import { ObjectiveCard } from './ObjectiveCard';

import type { CyberObjective } from '@/types/workspace';

export interface ObjectiveListProps {
  objectives: CyberObjective[];
  onEdit?: ((objective: CyberObjective) => void) | undefined;
  onDelete?: ((objectiveId: string) => void) | undefined;
  onProject?: ((objectiveId: string) => void) | undefined;
  onCreate?: (() => void) | undefined;
  loading?: boolean | undefined;
}

export const ObjectiveList: React.FC<ObjectiveListProps> = ({
  objectives,
  onEdit,
  onDelete,
  onProject,
  onCreate,
  loading = false,
}) => {
  const { t } = useTranslation();
  const { topLevel, childrenMap } = useMemo(() => {
    const roots: CyberObjective[] = [];
    const nestedChildren = new Map<string, CyberObjective[]>();

    objectives.forEach((objective) => {
      if (!objective.parent_id) {
        roots.push(objective);
      } else {
        const children = nestedChildren.get(objective.parent_id) || [];
        children.push(objective);
        nestedChildren.set(objective.parent_id, children);
      }
    });

    roots.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

    return { topLevel: roots, childrenMap: nestedChildren };
  }, [objectives]);

  if (loading) {
    return (
      <div className="space-y-3">
        <Skeleton active paragraph={{ rows: 1 }} />
        <Skeleton active paragraph={{ rows: 1 }} />
      </div>
    );
  }

  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Target
            size={16}
            className="text-text-muted dark:text-text-muted"
          />
          <h3 className="text-sm font-semibold text-text-primary dark:text-text-inverse">
            {t('blackboard.objectivesTitle', 'Goals')}
          </h3>
        </div>
        {onCreate && (
          <Button
            type="text"
            size="small"
            icon={<Plus size={14} />}
            onClick={onCreate}
            className="text-xs text-text-secondary hover:text-text-primary dark:text-text-muted dark:hover:text-text-inverse"
          >
            {t('workspaceDetail.objectives.addObjective')}
          </Button>
        )}
      </div>

      {topLevel.length === 0 ? (
        <div className="flex items-center justify-center rounded-xl border border-dashed border-border-separator bg-surface-light/50 px-4 py-6 text-center dark:border-border-dark dark:bg-surface-dark/50">
          <div className="max-w-sm">
            <p className="text-sm text-text-secondary dark:text-text-muted">
              {t(
                'workspaceDetail.objectives.emptySummary',
                'Start with one shared objective so the blackboard has a clear outcome to anchor tasks and discussion.'
              )}
            </p>
            {onCreate && (
              <Button type="primary" size="small" onClick={onCreate} className="mt-3">
                {t('workspaceDetail.objectives.createFirst')}
              </Button>
            )}
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          {topLevel.map((parent) => (
            <div key={parent.id} className="space-y-2">
              <ObjectiveCard
                objective={parent}
                onEdit={onEdit}
                onDelete={onDelete}
                onProject={onProject}
              />

              {childrenMap.has(parent.id) && (
                <div className="ml-4 space-y-2 border-l-2 border-border-light pl-3 dark:border-border-dark">
                  {childrenMap.get(parent.id)?.map((child) => (
                    <ObjectiveCard
                      key={child.id}
                      objective={child}
                      onEdit={onEdit}
                      onDelete={onDelete}
                      onProject={onProject}
                    />
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
};
