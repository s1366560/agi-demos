import React from 'react';

import { useParams } from 'react-router-dom';

import { AgentTeammatesPanel } from '@/components/project/AgentTeammatesPanel';
import { UserManager } from '@/components/tenant/UserManager';

export const Team: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  return (
    <div className="space-y-6 p-4 sm:p-6 lg:p-8">
      <UserManager context="project" />
      {projectId && <AgentTeammatesPanel projectId={projectId} />}
    </div>
  );
};
