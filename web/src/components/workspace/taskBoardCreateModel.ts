import type { WorkspaceTaskPriority } from '@/types/workspace';

export function buildTaskCreatePayload({
  title,
  priority,
  effort,
  blockerReason,
}: {
  title: string;
  priority: WorkspaceTaskPriority;
  effort: string;
  blockerReason: string;
}) {
  return {
    title,
    ...(priority ? { priority } : {}),
    ...(effort ? { estimated_effort: effort } : {}),
    ...(blockerReason.trim() ? { blocker_reason: blockerReason.trim() } : {}),
  };
}
