import { useTenantStore } from '@/stores/tenant';
import { OrgClustersView } from './OrgClustersView';

export function OrgClusters() {
  const tenantId = useTenantStore((s) => s.currentTenant?.id);
  return <OrgClustersView tenantId={tenantId} />;
}

export default OrgClusters;
