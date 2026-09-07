import type { ComponentProps } from 'react';

import { DesktopStatusBar } from '../features/chrome/DesktopStatusBar';

export type DesktopStatusBarInputV2 = Readonly<ComponentProps<typeof DesktopStatusBar>>;

export interface DesktopStatusBarSurfacePropsV2 {
  readonly input: DesktopStatusBarInputV2;
}

export function DesktopStatusBarSurfaceV2({ input }: DesktopStatusBarSurfacePropsV2) {
  return <DesktopStatusBar {...input} />;
}
