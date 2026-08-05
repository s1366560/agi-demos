import type { ChangeSnapshot, DesktopRunInput } from '../../types';
import type { CloudRunInputReceipt, RunChanges } from './agentAuthorityTypes';

export function desktopRunInputFromCloud(
  input: CloudRunInputReceipt,
): DesktopRunInput {
  return {
    ...input,
    references: input.references.map((reference) => ({ ...reference })),
    context_items: input.context_items.map(({ metadata, ...item }) =>
      metadata === null ? item : { ...item, metadata: { ...metadata } },
    ),
  };
}

export function desktopChangeSnapshotFromCloud(
  snapshot: RunChanges,
): ChangeSnapshot {
  return {
    id: snapshot.id,
    run_id: snapshot.run_id,
    conversation_id: snapshot.conversation_id,
    run_revision: snapshot.run_revision,
    environment_id: snapshot.environment_id,
    repository_root: snapshot.repository_root,
    workspace_path: snapshot.workspace_path,
    branch: snapshot.branch,
    base_revision: snapshot.base_revision,
    head_revision: snapshot.head_revision,
    status: snapshot.status,
    reason: snapshot.reason,
    additions: snapshot.additions,
    deletions: snapshot.deletions,
    files_changed: snapshot.files_changed,
    truncated: snapshot.truncated,
    captured_at: snapshot.captured_at,
    scope: snapshot.scope,
    turn_id: snapshot.turn_id,
    snapshot_revision: snapshot.snapshot_revision,
    attribution: snapshot.attribution.map((entry) => ({
      ...entry,
      payload: { ...entry.payload },
    })),
    files: snapshot.files.map((file) => ({
      ...file,
      hunks: file.hunks.map((hunk) => ({
        ...hunk,
        lines: hunk.lines.map((line) => ({ ...line })),
      })),
    })),
  };
}
