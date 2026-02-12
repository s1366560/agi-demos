/**
 * SubAgentGrid - Responsive grid layout for SubAgent cards.
 */

import { memo } from 'react';

import { SubAgentCard } from './SubAgentCard';

import type { SubAgentResponse } from '../../types/agent';

interface SubAgentGridProps {
  subagents: SubAgentResponse[];
  onToggle: (id: string, enabled: boolean) => void;
  onEdit: (subagent: SubAgentResponse) => void;
  onDelete: (id: string) => void;
  onExport?: (subagent: SubAgentResponse) => void;
}

export const SubAgentGrid = memo<SubAgentGridProps>(
  ({ subagents, onToggle, onEdit, onDelete, onExport }) => (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      {subagents.map((subagent) => (
        <SubAgentCard
          key={subagent.id}
          subagent={subagent}
          onToggle={onToggle}
          onEdit={onEdit}
          onDelete={onDelete}
          onExport={onExport}
        />
      ))}
    </div>
  ),
);

SubAgentGrid.displayName = 'SubAgentGrid';
