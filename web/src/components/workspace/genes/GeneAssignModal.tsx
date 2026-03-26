import React, { useEffect, useState } from 'react';

import { Modal, Checkbox, Tag, Typography } from 'antd';

import type { CyberGene } from '@/types/workspace';

import type { CheckboxOptionType } from 'antd';


export interface GeneAssignModalProps {
  open: boolean;
  agentName: string;
  availableGenes: CyberGene[];
  assignedGeneIds: string[];
  onConfirm: (selectedGeneIds: string[]) => void;
  onCancel: () => void;
}

export const GeneAssignModal: React.FC<GeneAssignModalProps> = ({
  open,
  agentName,
  availableGenes,
  assignedGeneIds,
  onConfirm,
  onCancel,
}) => {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  useEffect(() => {
    if (open) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelectedIds(assignedGeneIds);
    }
  }, [open, assignedGeneIds]);

  const handleOk = () => {
    onConfirm(selectedIds);
  };

  const onChange = (checkedValues: string[]) => {
    setSelectedIds(checkedValues);
  };

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

  const options: CheckboxOptionType[] = availableGenes.map((gene) => ({
    label: (
      <div className="flex items-center gap-2 py-1">
        <Typography.Text>{gene.name}</Typography.Text>
        <Tag color={getCategoryColor(gene.category)} className="m-0 border-transparent text-xs">
          {gene.category}
        </Tag>
        <Tag color="default" className="m-0 border-transparent text-xs">
          v{gene.version}
        </Tag>
      </div>
    ),
    value: gene.id,
  }));

  return (
    <Modal
      title={`Assign Genes to ${agentName}`}
      open={open}
      onOk={handleOk}
      onCancel={onCancel}
      destroyOnClose
      okText="Save Assignments"
    >
      <div className="py-4">
        {availableGenes.length === 0 ? (
          <Typography.Text type="secondary">
            No active genes available in this workspace.
          </Typography.Text>
        ) : (
          <Checkbox.Group
            className="flex flex-col gap-2"
            options={options}
            value={selectedIds}
            onChange={(values) => { onChange(values as string[]); }}
          />
        )}
      </div>
    </Modal>
  );
};
