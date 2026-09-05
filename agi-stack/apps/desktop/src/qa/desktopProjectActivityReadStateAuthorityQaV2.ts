import {
  createActivityReadStateOperationsTableV2,
  type DesktopProjectActivityReadStateOperationsV2,
} from '../plugins/desktopProjectActivityReadStateAuthorityModuleV2';
import { createDesktopProjectActivityReadStateHttpProjectionV2 } from '../plugins/desktopProjectActivityReadStateHttpProjectionV2';
import {
  prepareActivityReadStateInputV2,
  requireActivityReadStateResultV2,
  checkActivityReadStateAbortV2,
} from '../plugins/desktopProjectActivityReadStateOperationContractV2';
// Standalone QA exercises the protocol; it provides no Loader or native lease evidence.
export function createDesktopProjectActivityReadStateQaOperationsV2(): DesktopProjectActivityReadStateOperationsV2 {
  return createActivityReadStateOperationsTableV2(async (method, input) => {
    const p = prepareActivityReadStateInputV2(method, input);
    const raw = await createDesktopProjectActivityReadStateHttpProjectionV2(p.config).execute(
      method,
      p,
    );
    checkActivityReadStateAbortV2(p.signal);
    return requireActivityReadStateResultV2(method, raw, p);
  });
}
