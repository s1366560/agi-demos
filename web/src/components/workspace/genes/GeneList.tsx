import React, { useMemo, useState } from 'react';

import { PlusOutlined } from '@ant-design/icons';
import { Button, Empty, Skeleton, Typography, Segmented } from 'antd';

import { GeneCard } from './GeneCard';

import type { CyberGene } from '@/types/workspace';

export interface GeneListProps {
  genes: CyberGene[];
  loading?: boolean | undefined;
  onEdit?: ((gene: CyberGene) => void) | undefined;
  onDelete?: ((geneId: string) => void) | undefined;
  onToggleActive?: ((geneId: string, isActive: boolean) => void) | undefined;
  onCreate?: (() => void) | undefined;
}

export const GeneList: React.FC<GeneListProps> = ({
  genes,
  loading = false,
  onEdit,
  onDelete,
  onToggleActive,
  onCreate,
}) => {
  const [filterCategory, setFilterCategory] = useState<string>('All');

  const filteredGenes = useMemo(() => {
    let result = genes;
    if (filterCategory !== 'All') {
      result = genes.filter((g) => g.category.toLowerCase() === filterCategory.toLowerCase());
    }
    return result.sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    );
  }, [genes, filterCategory]);

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
          Cyber Genes
        </Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={onCreate}>
          Create Gene
        </Button>
      </div>

      <div className="mb-4">
        <Segmented
          options={['All', 'Skill', 'Knowledge', 'Tool', 'Workflow']}
          value={filterCategory}
          onChange={(value) => { setFilterCategory(value); }}
        />
      </div>

      <div className="flex-1 overflow-y-auto min-h-0 pr-2 space-y-3">
        {filteredGenes.length === 0 ? (
          <div className="h-full flex items-center justify-center">
            <Empty description="No genes found" image={Empty.PRESENTED_IMAGE_SIMPLE}>
              {filterCategory === 'All' && (
                <Button type="primary" onClick={onCreate}>
                  Create Your First Gene
                </Button>
              )}
            </Empty>
          </div>
        ) : (
          filteredGenes.map((gene) => (
            <GeneCard
              key={gene.id}
              gene={gene}
              onEdit={onEdit}
              onDelete={onDelete}
              onToggleActive={onToggleActive}
            />
          ))
        )}
      </div>
    </div>
  );
};
