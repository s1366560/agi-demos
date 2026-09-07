import {
  createSandboxSurfaceOperationsTableV2,
  type DesktopProjectSandboxSurfaceOperationsV2,
} from '../plugins/desktopProjectSandboxSurfaceAuthorityModuleV2';
import { createDesktopProjectSandboxSurfaceHttpProjectionV2 } from '../plugins/desktopProjectSandboxSurfaceHttpProjectionV2';
import { prepareSandboxSurfaceInputV2 } from '../plugins/desktopProjectSandboxSurfaceOperationContractV2';
import { requireSandboxSurfaceResultV2 } from '../plugins/desktopProjectSandboxSurfaceResponseContractV2';
// Standalone QA uses real preparation, projection and response contracts; it claims no native lease.
export function createDesktopProjectSandboxSurfaceQaOperationsV2(): DesktopProjectSandboxSurfaceOperationsV2 {
  return createSandboxSurfaceOperationsTableV2(async (method, input) => {
    const p = prepareSandboxSurfaceInputV2(method, input);
    const raw = await createDesktopProjectSandboxSurfaceHttpProjectionV2(p.config).execute(
      method,
      p,
    );
    if (p.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const result = requireSandboxSurfaceResultV2(method, raw, p);
    if (method === 'openRemoteDesktop' && 'status' in result && result.status === 'ready') {
      return Object.freeze({
        status: 'ready',
        value: Object.freeze({ ...result.value, release: async () => undefined }),
      }) as unknown as typeof result;
    }
    return result;
  });
}
