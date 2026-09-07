import {
  createMcpAppsOperationsTableV2,
  type DesktopProjectMcpAppsOperationsV2,
} from '../plugins/desktopProjectMcpAppsAuthorityModuleV2';
import { createDesktopProjectMcpAppsHttpProjectionV2 } from '../plugins/desktopProjectMcpAppsHttpProjectionV2';
import { prepareMcpAppsInputV2 } from '../plugins/desktopProjectMcpAppsOperationContractV2';
import { requireMcpAppsResultV2 } from '../plugins/desktopProjectMcpAppsResponseContractV2';
// Standalone QA uses real preparation, projection and response contracts; it claims no native lease.
export function createDesktopProjectMcpAppsQaOperationsV2(): DesktopProjectMcpAppsOperationsV2 {
  return createMcpAppsOperationsTableV2(async (method, input) => {
    const p = prepareMcpAppsInputV2(method, input);
    const raw = await createDesktopProjectMcpAppsHttpProjectionV2(p.config).execute(method, p);
    if (p.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    return requireMcpAppsResultV2(method, raw, p);
  });
}
