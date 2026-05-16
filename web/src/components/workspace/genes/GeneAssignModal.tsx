import { useEffect, useState } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Checkbox, Modal, Tag, Typography } from 'antd';

import { getCategoryColor } from './utils';

import type { CyberGene } from '@/types/workspace';

export interface GeneAssignModalProps {
  open: boolean;
  agentName: string;
  availableGenes: CyberGene[];
  assignedGeneIds: string[];
  onConfirm: (selectedGeneIds: string[]) => void;
  onCancel: () => void;
}

export const GeneAssignModal: FC<GeneAssignModalProps> = ({
  open,
  agentName,
  availableGenes,
  assignedGeneIds,
  onConfirm,
  onCancel,
}) => {
  const { t } = useTranslation();
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

  const options = availableGenes.map((gene) => ({
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
      title={t('workspaceDetail.genes.assignTitle', {
        agentName,
        defaultValue: 'Assign Genes to {{agentName}}',
      })}
      open={open}
      onOk={handleOk}
      onCancel={onCancel}
      destroyOnHidden
      okText={t('workspaceDetail.genes.saveAssignments', 'Save Assignments')}
      cancelText={t('common.cancel', 'Cancel')}
    >
      <div className="py-4">
        {availableGenes.length === 0 ? (
          <Typography.Text type="secondary">
            {t(
              'workspaceDetail.genes.noActiveGenes',
              'No active genes available in this workspace.'
            )}
          </Typography.Text>
        ) : (
          <Checkbox.Group
            className="flex flex-col gap-2"
            options={options}
            value={selectedIds}
            onChange={(values) => {
              onChange(values);
            }}
          />
        )}
      </div>
    </Modal>
  );
};
