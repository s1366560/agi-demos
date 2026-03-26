import React from 'react';

import { MoreOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons';
import { Card, Tag, Dropdown, Typography } from 'antd';

import { ObjectiveProgress } from './ObjectiveProgress';

import type { CyberObjective } from '@/types/workspace';

import type { MenuProps } from 'antd';


export interface ObjectiveCardProps {
  objective: CyberObjective;
  onEdit?: ((objective: CyberObjective) => void) | undefined;
  onDelete?: ((objectiveId: string) => void) | undefined;
}

export const ObjectiveCard: React.FC<ObjectiveCardProps> = ({ objective, onEdit, onDelete }) => {
  const isObjective = objective.obj_type === 'objective';
  const badgeColor = isObjective ? 'blue' : 'green';
  const badgeText = isObjective ? 'Objective' : 'Key Result';

  const menuItems: MenuProps['items'] = [
    {
      key: 'edit',
      icon: <EditOutlined />,
      label: 'Edit',
      onClick: () => onEdit?.(objective),
    },
    {
      key: 'delete',
      icon: <DeleteOutlined className="text-red-500" />,
      label: <span className="text-red-500">Delete</span>,
      onClick: () => onDelete?.(objective.id),
    },
  ];

  return (
    <Card
      size="small"
      className="w-full hover:shadow-sm transition-shadow border-slate-200"
      styles={{ body: { padding: '12px 16px' } }}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <Tag color={badgeColor} className="m-0 border-transparent font-medium">
              {badgeText}
            </Tag>
            <Typography.Text className="text-xs text-slate-400">
              Created: {new Date(objective.created_at).toLocaleDateString()}
            </Typography.Text>
          </div>
          <Typography.Title level={5} className="m-0 truncate" title={objective.title}>
            {objective.title}
          </Typography.Title>
          {objective.description && (
            <Typography.Paragraph
              className="m-0 text-slate-500 text-sm mt-1"
              ellipsis={{ rows: 2, tooltip: objective.description }}
            >
              {objective.description}
            </Typography.Paragraph>
          )}
        </div>

        <div className="flex items-center gap-4 flex-shrink-0">
          <ObjectiveProgress progress={objective.progress} size={40} strokeWidth={4} />

          <Dropdown menu={{ items: menuItems }} trigger={['click']} placement="bottomRight">
            <div className="p-1 cursor-pointer rounded hover:bg-slate-100 transition-colors text-slate-400 hover:text-slate-600">
              <MoreOutlined className="text-lg" />
            </div>
          </Dropdown>
        </div>
      </div>
    </Card>
  );
};
