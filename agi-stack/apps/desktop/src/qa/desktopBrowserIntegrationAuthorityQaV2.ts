import {
  createBrowserIntegrationOperationsTableV2,
  type DesktopBrowserIntegrationOperationsV2,
} from '../plugins/desktopBrowserIntegrationAuthorityModuleV2';
import { createDesktopBrowserIntegrationHttpProjectionV2 } from '../plugins/desktopBrowserIntegrationHttpProjectionV2';
import { prepareBrowserIntegrationInputV2 } from '../plugins/desktopBrowserIntegrationOperationContractV2';
import { requireBrowserIntegrationResultV2 } from '../plugins/desktopBrowserIntegrationResponseContractV2';
// Standalone QA uses real preparation, projection and response contracts; it claims no native lease.
export function createDesktopBrowserIntegrationQaOperationsV2(): DesktopBrowserIntegrationOperationsV2 {
  return createBrowserIntegrationOperationsTableV2(async (method, input) => {
    const p = prepareBrowserIntegrationInputV2(method, input);
    const raw = await createDesktopBrowserIntegrationHttpProjectionV2(p.config).execute(method, p);
    if (p.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    return requireBrowserIntegrationResultV2(method, raw, p);
  });
}
