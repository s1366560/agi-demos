import type { ComponentProps } from 'react';

import { KeyboardShortcutsDialog } from '../features/navigation/KeyboardShortcutsDialog';

export type DesktopKeyboardShortcutsInputV2 = Readonly<
  ComponentProps<typeof KeyboardShortcutsDialog>
>;

export interface DesktopKeyboardShortcutsSurfacePropsV2 {
  readonly input: DesktopKeyboardShortcutsInputV2;
}

export function DesktopKeyboardShortcutsSurfaceV2({
  input,
}: DesktopKeyboardShortcutsSurfacePropsV2) {
  return <KeyboardShortcutsDialog {...input} />;
}
