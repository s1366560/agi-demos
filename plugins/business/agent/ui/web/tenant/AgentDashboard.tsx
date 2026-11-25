import { memo } from 'react';
import { useParams } from 'react-router-dom';
import { useTenantStore } from '@/stores/tenant';
import { TenantAgentDashboardContent } from './TenantAgentDashboardContent';

export const AgentDashboard = memo(() => {
  const { tenantId: routeTenantId } = useParams<{ tenantId: string }>();
  const currentTenantId = useTenantStore((state) => state.currentTenant?.id ?? null);
  const tenantId = routeTenantId ?? currentTenantId ?? null;
  return <TenantAgentDashboardContent tenantId={tenantId} />;
});

AgentDashboard.displayName = 'AgentDashboard';
export default AgentDashboard;
