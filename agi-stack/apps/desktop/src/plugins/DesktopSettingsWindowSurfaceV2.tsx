import type { ComponentProps } from 'react';

import { SettingsWindow } from '../features/settings/SettingsWindow';

export type DesktopSettingsWindowInputV2 = Readonly<ComponentProps<typeof SettingsWindow>>;

export interface DesktopSettingsWindowSurfacePropsV2 {
  readonly input: DesktopSettingsWindowInputV2;
}

export function DesktopSettingsWindowSurfaceV2({
  input,
}: DesktopSettingsWindowSurfacePropsV2) {
  return <SettingsWindow {...input} />;
}
