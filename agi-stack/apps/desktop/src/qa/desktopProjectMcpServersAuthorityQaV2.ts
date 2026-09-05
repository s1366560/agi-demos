import {
  createMcpServersOperationsTableV2,
  type DesktopProjectMcpServersOperationsV2,
} from '../plugins/desktopProjectMcpServersAuthorityModuleV2';
import { createDesktopProjectMcpServersHttpProjectionV2 } from '../plugins/desktopProjectMcpServersHttpProjectionV2';
import { prepareMcpServersInputV2 } from '../plugins/desktopProjectMcpServersOperationContractV2';
import { requireMcpServersResultV2 } from '../plugins/desktopProjectMcpServersResponseContractV2';
// Standalone QA uses real preparation, projection and response contracts; it claims no native lease.
export function createDesktopProjectMcpServersQaOperationsV2(): DesktopProjectMcpServersOperationsV2 {
  return createMcpServersOperationsTableV2(async (method, input) => {
    const p = prepareMcpServersInputV2(method, input);
    const raw = await createDesktopProjectMcpServersHttpProjectionV2(p.config).execute(method, p);
    if (p.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    return requireMcpServersResultV2(method, raw, p);
  });
}
