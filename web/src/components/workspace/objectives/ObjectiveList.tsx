import React, { useMemo } from 'react';

import { PlusOutlined } from '@ant-design/icons';
import { Button, Empty, Skeleton, Typography } from 'antd';

import { ObjectiveCard } from './ObjectiveCard';

import type { CyberObjective } from '@/types/workspace';

export interface ObjectiveListProps {
  objectives: CyberObjective[];
  onEdit?: ((objective: CyberObjective) => void) | undefined;
  onDelete?: ((objectiveId: string) => void) | undefined;
  onCreate?: (() => void) | undefined;
  loading?: boolean | undefined;
}

export const ObjectiveList: React.FC<ObjectiveListProps> = ({
  objectives,
  onEdit,
  onDelete,
  onCreate,
  loading = false,
}) => {
  const { topLevel, childrenMap } = useMemo(() => {
    const topLevel: CyberObjective[] = [];
    const childrenMap = new Map<string, CyberObjective[]>();

    objectives.forEach((obj) => {
      if (!obj.parent_id) {
        topLevel.push(obj);
      } else {
        const children = childrenMap.get(obj.parent_id) || [];
        children.push(obj);
        childrenMap.set(obj.parent_id, children);
      }
    });

    topLevel.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

    return { topLevel, childrenMap };
  }, [objectives]);

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton active paragraph={{ rows: 2 }} />
        <Skeleton active paragraph={{ rows: 2 }} />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full w-full">
      <div className="flex items-center justify-between mb-4">
        <Typography.Title level={4} className="m-0">
          Objectives & Key Results
        </Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={onCreate}>
          Add Objective
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0 pr-2 space-y-6">
        {topLevel.length === 0 ? (
          <div className="h-full flex items-center justify-center">
            <Empty description="No objectives found" image={Empty.PRESENTED_IMAGE_SIMPLE}>
              <Button type="primary" onClick={onCreate}>
                Create Your First Objective
              </Button>
            </Empty>
          </div>
        ) : (
          topLevel.map((parent) => (
            <div key={parent.id} className="space-y-2">
              <ObjectiveCard objective={parent} onEdit={onEdit} onDelete={onDelete} />

              {childrenMap.has(parent.id) && (
                <div className="pl-6 md:pl-8 border-l-2 border-slate-100 ml-4 space-y-2 mt-2">
                  {childrenMap.get(parent.id)?.map((child) => (
                    <ObjectiveCard
                      key={child.id}
                      objective={child}
                      onEdit={onEdit}
                      onDelete={onDelete}
                    />
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
};
