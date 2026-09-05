import {
  createProviderOperationsTableV2,
  type DesktopTenantProvidersOperationsV2,
} from '../plugins/desktopTenantProvidersAuthorityModuleV2';
import { createDesktopTenantProvidersHttpProjectionV2 } from '../plugins/desktopTenantProvidersHttpProjectionV2';
import {
  prepareProviderInputV2,
  requireProviderResultV2,
} from '../plugins/desktopTenantProvidersOperationContractV2';
// Standalone QA uses production preparation, projection and response contracts, without claiming a native Loader lease.
export function createDesktopTenantProvidersQaOperationsV2(): DesktopTenantProvidersOperationsV2 {
  return createProviderOperationsTableV2(async (method, input) => {
    const p = prepareProviderInputV2(method, input);
    const raw = await createDesktopTenantProvidersHttpProjectionV2(p.config).execute(method, p);
    if (p.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    return requireProviderResultV2(method, raw, p);
  });
}
