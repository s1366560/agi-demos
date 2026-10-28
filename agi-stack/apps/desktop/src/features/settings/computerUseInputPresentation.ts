import type { ComputerUsePresentation } from '../../api/computerUseContractV2';
import { computerUseInputIsVisible, type ComputerUseInput } from '../../api/computerUseInput';

export type ImageBounds = Readonly<{
  x: number;
  y: number;
  width: number;
  height: number;
}>;

export function computerUseInputMatchesPreview(
  input: ComputerUseInput | null,
  presentation: ComputerUsePresentation,
): input is ComputerUseInput {
  const target = presentation.target;
  const window = presentation.preview?.window_id ?? target?.window_id;
  return (
    !!input &&
    computerUseInputIsVisible(input) &&
    !['paused', 'stopped', 'awaiting_permission', 'focus_required', 'error'].includes(
      presentation.phase,
    ) &&
    target?.process_id === input.target_pid &&
    !!window &&
    window === input.target_window_id &&
    (!target.window_id || target.window_id === window)
  );
}

/** Preserve the observed screenshot's aspect ratio, including object-fit letterboxing. */
export function computerUseContainedImageBounds(
  width: number,
  height: number,
  naturalWidth: number,
  naturalHeight: number,
): ImageBounds | null {
  if (
    ![width, height, naturalWidth, naturalHeight].every(
      (value) => Number.isFinite(value) && value > 0,
    )
  )
    return null;
  const scale = Math.min(width / naturalWidth, height / naturalHeight);
  const fittedWidth = naturalWidth * scale;
  const fittedHeight = naturalHeight * scale;
  return {
    x: (width - fittedWidth) / 2,
    y: (height - fittedHeight) / 2,
    width: fittedWidth,
    height: fittedHeight,
  };
}

export function computerUseCursorPosition(
  input: ComputerUseInput,
  bounds: ImageBounds | null,
): Readonly<{ x: number; y: number }> | null {
  const cursor = input.virtual_cursor;
  if (
    !cursor ||
    !bounds ||
    cursor.window_id !== input.target_window_id ||
    cursor.x < 0 ||
    cursor.y < 0 ||
    cursor.x > cursor.width ||
    cursor.y > cursor.height
  )
    return null;
  return {
    x: bounds.x + (cursor.x / cursor.width) * bounds.width,
    y: bounds.y + (cursor.y / cursor.height) * bounds.height,
  };
}

/** macOS virtual-key codes identify modifiers structurally; ordinary keys stay undisplayed. */
export function computerUseHeldLabels(input: ComputerUseInput): readonly string[] {
  const modifiers: readonly [string, readonly number[]][] = [
    ['command', [54, 55]],
    ['shift', [56, 60]],
    ['option', [58, 61]],
    ['control', [59, 62]],
    ['fn', [63]],
  ];
  const buttons = ['left', 'right', 'middle'] as const;
  return [
    ...buttons.flatMap((button, code) =>
      input.held_buttons.includes(code) ? [`cua.input.button.${button}`] : [],
    ),
    ...(input.held_buttons.some((button) => button > 2) ? ['cua.input.button.additional'] : []),
    ...modifiers.flatMap(([name, codes]) =>
      codes.some((code) => input.held_keys.includes(code)) ? [`cua.input.modifier.${name}`] : [],
    ),
  ];
}
