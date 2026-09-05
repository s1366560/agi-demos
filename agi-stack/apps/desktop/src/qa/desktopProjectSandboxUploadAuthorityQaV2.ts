import type { DesktopProjectSandboxUploadOperationsV2 } from '../plugins/desktopProjectSandboxUploadAuthorityModuleV2';
import { createDesktopProjectSandboxUploadHttpProjectionV2 } from '../plugins/desktopProjectSandboxUploadHttpProjectionV2';
import {
  checkSandboxUploadAbortV2,
  prepareSandboxUploadInputV2,
  type ProjectSandboxUploadInputV2,
} from '../plugins/desktopProjectSandboxUploadOperationContractV2';
import { requireSandboxUploadResultV2 } from '../plugins/desktopProjectSandboxUploadResponseContractV2';
// Standalone QA shares real contracts and HTTP projection; it claims no Loader or native lease.
export function createDesktopProjectSandboxUploadQaOperationsV2(): DesktopProjectSandboxUploadOperationsV2 {
  return Object.freeze({
    async uploadSandboxFile(input: ProjectSandboxUploadInputV2) {
      const p = prepareSandboxUploadInputV2(input);
      const raw = await createDesktopProjectSandboxUploadHttpProjectionV2(
        p.config,
      ).uploadSandboxFile(p);
      checkSandboxUploadAbortV2(p.signal);
      return requireSandboxUploadResultV2(raw, p);
    },
  });
}
