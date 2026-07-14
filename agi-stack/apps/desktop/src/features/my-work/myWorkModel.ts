import type { AgentCapabilityMode, MyWorkGroup, ProjectWorkItem } from '../../types';

export const MY_WORK_GROUPS: MyWorkGroup[] = [
  'needs_input',
  'needs_approval',
  'running',
  'ready_review',
];

export type MyWorkModeFilter = 'all' | AgentCapabilityMode;

export function filterMyWorkItems(
  items: ProjectWorkItem[],
  group: MyWorkGroup | 'all',
  mode: MyWorkModeFilter,
): ProjectWorkItem[] {
  return items
    .filter((item) => group === 'all' || item.group === group)
    .filter((item) => mode === 'all' || item.capability_mode === mode)
    .sort(
      (left, right) =>
        Date.parse(right.updated_at || right.created_at) -
        Date.parse(left.updated_at || left.created_at),
    );
}

export function countMyWorkGroups(items: ProjectWorkItem[]): Record<MyWorkGroup, number> {
  return MY_WORK_GROUPS.reduce<Record<MyWorkGroup, number>>(
    (counts, group) => {
      counts[group] = items.filter((item) => item.group === group).length;
      return counts;
    },
    { needs_input: 0, needs_approval: 0, running: 0, ready_review: 0 },
  );
}
