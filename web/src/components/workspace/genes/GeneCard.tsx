import React from 'react';

import {
  MoreOutlined,
  EditOutlined,
  DeleteOutlined,
  CheckCircleOutlined,
  StopOutlined,
} from '@ant-design/icons';
import { Card, Tag, Dropdown, Typography } from 'antd';

import type { CyberGene } from '@/types/workspace';

import type { MenuProps } from 'antd';


export interface GeneCardProps {
  gene: CyberGene;
  onEdit?: ((gene: CyberGene) => void) | undefined;
  onDelete?: ((geneId: string) => void) | undefined;
  onToggleActive?: ((geneId: string, isActive: boolean) => void) | undefined;
}

export const GeneCard: React.FC<GeneCardProps> = ({ gene, onEdit, onDelete, onToggleActive }) => {
  const getCategoryColor = (category: string) => {
    switch (category) {
      case 'skill':
        return 'blue';
      case 'knowledge':
        return 'green';
      case 'tool':
        return 'orange';
      case 'workflow':
        return 'purple';
      default:
        return 'default';
    }
  };

  const getCategoryText = (category: string) => {
    return category.charAt(0).toUpperCase() + category.slice(1);
  };

  const menuItems: MenuProps['items'] = [
    {
      key: 'edit',
      icon: <EditOutlined />,
      label: 'Edit',
      onClick: () => onEdit?.(gene),
    },
    {
      key: 'toggle_active',
      icon: gene.is_active ? <StopOutlined /> : <CheckCircleOutlined />,
      label: gene.is_active ? 'Deactivate' : 'Activate',
      onClick: () => onToggleActive?.(gene.id, !gene.is_active),
    },
    {
      key: 'delete',
      icon: <DeleteOutlined className="text-red-500" />,
      label: <span className="text-red-500">Delete</span>,
      onClick: () => onDelete?.(gene.id),
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
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <Tag
              color={getCategoryColor(gene.category)}
              className="m-0 border-transparent font-medium"
            >
              {getCategoryText(gene.category)}
            </Tag>
            <Tag color="default" className="m-0 border-transparent text-xs">
              v{gene.version}
            </Tag>
            <Tag color={gene.is_active ? 'success' : 'error'} className="m-0 border-transparent">
              {gene.is_active ? 'Active' : 'Inactive'}
            </Tag>
          </div>
          <Typography.Title level={5} className="m-0 truncate" title={gene.name}>
            {gene.name}
          </Typography.Title>
          {gene.description && (
            <Typography.Paragraph
              className="m-0 text-slate-500 text-sm mt-1"
              ellipsis={{ rows: 2, tooltip: gene.description }}
            >
              {gene.description}
            </Typography.Paragraph>
          )}
        </div>

        <div className="flex items-center gap-4 flex-shrink-0">
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
