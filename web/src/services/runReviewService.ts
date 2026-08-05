import { httpClient } from './client/httpClient';

import type { RunSummary } from './projectWorkService';

export type ChangeScope = 'turn' | 'run' | 'session';
export type ChangeSnapshotStatus = 'ready' | 'unattributed' | 'unavailable' | 'failed';

export interface ChangeLine {
  kind: 'context' | 'addition' | 'deletion';
  old_line?: number | null;
  new_line?: number | null;
  text: string;
}

export interface ChangeHunk {
  id?: string | null;
  header: string;
  old_start: number;
  new_start: number;
  turn_id?: string | null;
  lines: ChangeLine[];
}

export interface ChangeFile {
  path: string;
  old_path?: string | null;
  status: string;
  additions: number;
  deletions: number;
  binary: boolean;
  untracked: boolean;
  patch_digest: string;
  turn_ids?: string[];
  hunks: ChangeHunk[];
}

export interface ChangeSnapshot {
  id: string;
  run_id: string;
  conversation_id: string;
  run_revision: number;
  scope: ChangeScope;
  turn_id?: string | null;
  status: ChangeSnapshotStatus;
  reason?: string | null;
  base_revision?: string | null;
  head_revision?: string | null;
  additions: number;
  deletions: number;
  files_changed: number;
  truncated: boolean;
  captured_at: string;
  files: ChangeFile[];
}

export interface GetChangesOptions {
  scope: ChangeScope;
  expected_revision: number;
  turn_id?: string;
}

const runPath = (runId: string): string => `/agent/runs/${encodeURIComponent(runId)}`;

export const runReviewService = {
  getSummary(runId: string): Promise<RunSummary> {
    return httpClient.get(`${runPath(runId)}/summary`);
  },

  getChanges(runId: string, options: GetChangesOptions): Promise<ChangeSnapshot> {
    return httpClient.get(`${runPath(runId)}/changes`, {
      params: {
        scope: options.scope,
        ...(options.turn_id ? { turn_id: options.turn_id } : {}),
        expected_revision: options.expected_revision,
      },
    });
  },
};
