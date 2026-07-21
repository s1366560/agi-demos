import React from 'react';

import { useTranslation } from 'react-i18next';

import { Dropdown } from 'antd';
import { Circle, MoreHorizontal, Pencil, PlayCircle, Trash2 } from 'lucide-react';

import { toPercent } from '@/utils/objectiveProgress';

import { calculateWorkspaceTaskCompletionRatio } from '@/components/blackboard/blackboardUtils';

import type { CyberObjective, WorkspaceTask } from '@/types/workspace';

import type { MenuProps } from 'antd';

export interface ObjectiveCardProps {
  objective: CyberObjective;
  tasks?: WorkspaceTask[] | undefined;
  completionRatio?: number | undefined;
  onEdit?: ((objective: CyberObjective) => void) | undefined;
  onDelete?: ((objectiveId: string) => void) | undefined;
  onProject?: ((objectiveId: string) => void) | undefined;
}

export const ObjectiveCard: React.FC<ObjectiveCardProps> = ({
  objective,
  tasks,
  completionRatio,
  onEdit,
  onDelete,
  onProject,
}) => {
  const { t } = useTranslation();
  const isObjective = objective.obj_type === 'objective';
  const progressColor = isObjective ? 'bg-primary' : 'bg-success';
  const progressPct = tasks
    ? (completionRatio ?? calculateWorkspaceTaskCompletionRatio(tasks))
    : toPercent(objective.progress);

  const menuItems: NonNullable<MenuProps['items']> = [
    ...(onEdit
      ? [
          {
            key: 'edit',
            icon: <Pencil size={14} />,
            label: t('workspaceDetail.objectives.edit'),
            onClick: () => {
              onEdit(objective);
            },
          },
        ]
      : []),
    ...(onDelete
      ? [
          {
            key: 'delete',
            icon: (
              <Trash2
                size={14}
                className="text-status-text-error dark:text-status-text-error-dark"
              />
            ),
            label: (
              <span className="text-status-text-error dark:text-status-text-error-dark">
                {t('workspaceDetail.objectives.delete')}
              </span>
            ),
            onClick: () => {
              onDelete(objective.id);
            },
          },
        ]
      : []),
    ...(onProject
      ? [
          {
            key: 'project',
            icon: <PlayCircle size={14} />,
            label: t('workspaceDetail.objectives.startExecution'),
            onClick: () => {
              onProject(objective.id);
            },
          },
        ]
      : []),
  ];

  return (
    <article className="group min-w-0 overflow-hidden rounded-xl border border-border-light bg-surface-light px-4 py-3 transition-colors hover:border-border-separator dark:border-border-dark dark:bg-surface-dark">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-start gap-2.5">
          <Circle size={16} className="mt-0.5 flex-none text-primary dark:text-primary-200" />
          <div className="min-w-0 flex-1">
            <h4 className="break-words text-sm font-semibold text-text-primary dark:text-text-inverse">
              {objective.title}
            </h4>
            {objective.description && (
              <p
                className="mt-1 line-clamp-2 break-words text-xs leading-5 text-text-secondary dark:text-text-muted"
                title={objective.description}
              >
                {objective.description}
              </p>
            )}
          </div>
        </div>

        <div className="flex flex-none items-center gap-2">
          <span className="text-sm font-medium text-text-secondary dark:text-text-muted">
            {progressPct}%
          </span>
          {menuItems.length > 0 && (
            <Dropdown menu={{ items: menuItems }} trigger={['click']} placement="bottomRight">
              <button
                type="button"
                aria-label={t('workspaceDetail.objectives.openActions', {
                  name: objective.title,
                })}
                className="inline-flex h-7 w-7 items-center justify-center rounded-md text-text-muted opacity-0 transition hover:bg-surface-muted hover:text-text-primary focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 group-focus-within:opacity-100 group-hover:opacity-100 dark:text-text-muted dark:hover:bg-background-dark dark:hover:text-text-inverse"
              >
                <MoreHorizontal size={16} />
              </button>
            </Dropdown>
          )}
        </div>
      </div>

      <div className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-border-light dark:bg-border-dark">
        <div
          className={`h-full rounded-full transition-[width,background-color] duration-500 ease-out ${progressColor}`}
          style={{ width: `${String(progressPct)}%` }}
        />
      </div>
    </article>
  );
};
