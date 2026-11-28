import { useParams } from 'react-router-dom';

// The signed page mounts with the tenant and project from the host context.
export function useProjectStore() {
  const { tenantId } = useParams();
  return { currentProject: { tenant_id: tenantId } };
}
