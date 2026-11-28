import type {
  ActivityReadState,
  ProjectMyWorkResponse,
  UpdateActivityReadStateRequest,
} from '../../../../../web/src/services/projectWorkService';
import type {
  ChangeSnapshot,
  GetChangesOptions,
} from '../../../../../web/src/services/runReviewService';
import type { RunSummary } from '../../../../../web/src/services/projectWorkService';
import type { RichPageCallOptions } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';

export function invoke<T>(
  command: string,
  payload: Record<string, unknown>,
  options?: RichPageCallOptions
) {
  return window.memstack.invoke(command, payload, options) as Promise<T>;
}

// The signed document is bound to one project. Its caller cannot supply a different project.
export const projectWorkService = {
  list(_project: string, options?: RichPageCallOptions) {
    return invoke<ProjectMyWorkResponse & { principal_id: string }>(
      'activity-list',
      { view: 'items' },
      options
    );
  },
  getReadState(_project: string, options?: RichPageCallOptions) {
    return invoke<ActivityReadState & { principal_id: string }>(
      'activity-list',
      { view: 'receipts' },
      options
    );
  },
  updateReadState(
    _project: string,
    request: UpdateActivityReadStateRequest,
    options?: RichPageCallOptions
  ) {
    return invoke<ActivityReadState>('activity-mark', { ...request }, options);
  },
};
export const runReviewService = {
  getSummary(runId: string) {
    return invoke<RunSummary>('review-details', { run_id: runId, view: 'summary' });
  },
  getChanges(runId: string, options: GetChangesOptions) {
    return invoke<ChangeSnapshot>('review-details', { run_id: runId, view: 'changes', ...options });
  },
};
