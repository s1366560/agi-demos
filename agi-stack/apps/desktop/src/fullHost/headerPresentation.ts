export const COMPACT_HEADER_QUERY = '(max-width: 1279px)';
export const NARROW_SHELL_QUERY = '(max-width: 767px)';

export type HeaderGroupView = {
  readonly id: string;
  readonly label: string;
  readonly current: boolean;
  readonly items: readonly {
    readonly id: string;
    readonly label: string;
    readonly path: string;
    readonly active: boolean;
  }[];
};

/** Below the web xl breakpoint the groups collapse into one menu. */
export function presentHeaderGroups(
  groups: readonly HeaderGroupView[],
  compact: boolean,
): HeaderGroupView[] {
  if (!compact || groups.length <= 1) return [...groups];
  const current = groups.find((group) => group.current);
  return [
    {
      id: 'compact-navigation',
      label: current?.label ?? groups[0]?.label ?? '',
      current: groups.some((group) => group.current),
      items: groups.flatMap((group) => group.items),
    },
  ];
}
