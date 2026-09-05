import type { DesktopSessionRunSummaryOperationInputV2 } from '../plugins/desktopSessionProjectionAuthorityModuleV2';
import type { DesktopSessionRunChangesOperationInputV2 } from '../plugins/desktopSessionRunChangesAuthorityModuleV2';
import { createDesktopRunReviewHttpProjectionV2 } from '../plugins/desktopRunReviewHttpProjectionV2';
// Standalone QA uses the real HTTP/response contract; it supplies no Loader/native lease evidence.
export function createDesktopRunReviewQaOperationsV2() {
  const identity = (
    input: DesktopSessionRunSummaryOperationInputV2 | DesktopSessionRunChangesOperationInputV2,
  ) =>
    Object.freeze({
      id: input.conversation.id,
      tenant_id: input.conversation.tenant_id,
      project_id: input.conversation.project_id,
      workspace_id: input.conversation.workspace_id ?? null,
    });
  return Object.freeze({
    getRunSummary: (input: DesktopSessionRunSummaryOperationInputV2) =>
      createDesktopRunReviewHttpProjectionV2(input.config).getRunSummary(
        identity(input),
        input.runId,
        input.signal,
      ),
    getRunChanges: (input: DesktopSessionRunChangesOperationInputV2) =>
      createDesktopRunReviewHttpProjectionV2(input.config).getRunChanges(
        identity(input),
        input.runId,
        input.expectedRevision,
        input.signal,
        { scope: input.scope, turnId: input.turnId },
      ),
  });
}
