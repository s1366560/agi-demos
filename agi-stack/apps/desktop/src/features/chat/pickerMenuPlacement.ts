export type PickerMenuPlacement = 'up' | 'down' | 'left' | 'right';

export type PickerMenuPlacementInput = {
  anchor: { top: number; right: number; bottom: number; left: number };
  viewport: { width: number; height: number };
  menuWidth: number;
  menuHeight: number;
  padding?: number;
};

/**
 * Keep composer pickers inside the usable window. Side placement is preferred
 * so a long model list never covers the input or the custom titlebar; vertical
 * placement is only used when neither side has room.
 */
export function resolvePickerMenuPlacement(
  input: PickerMenuPlacementInput,
): PickerMenuPlacement {
  const padding = input.padding ?? 8;
  const spaceRight = input.viewport.width - input.anchor.right - padding;
  const spaceLeft = input.anchor.left - padding;
  const spaceAbove = input.anchor.top - padding;
  const spaceBelow = input.viewport.height - input.anchor.bottom - padding;

  if (spaceRight >= input.menuWidth) return 'right';
  if (spaceLeft >= input.menuWidth) return 'left';
  if (spaceAbove >= input.menuHeight) return 'up';
  if (spaceBelow >= input.menuHeight) return 'down';
  return spaceAbove >= spaceBelow ? 'up' : 'down';
}
