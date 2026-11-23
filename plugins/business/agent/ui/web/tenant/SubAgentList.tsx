/**
 * SubAgentList - legacy route shim.
 *
 * SubAgent management has moved to the Agent Definitions page. This component
 * only redirects so existing `/tenant(/:tenantId)/subagents` links keep working.
 */

import type { FC } from 'react';

import { Navigate, useParams } from 'react-router-dom';

export const SubAgentList: FC = () => {
  const { tenantId } = useParams<{ tenantId?: string | undefined }>();

  return (
    <Navigate
      to={tenantId ? `/tenant/${tenantId}/agent-definitions` : '/tenant/agent-definitions'}
      replace
    />
  );
};

export default SubAgentList;
