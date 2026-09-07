import type { ComponentProps } from 'react';

import { WorkbenchTabBar } from '../features/chrome/WorkbenchTabBar';

export type DesktopWorkbenchTabBarInputV2 = Readonly<
  ComponentProps<typeof WorkbenchTabBar>
>;

export interface DesktopWorkbenchTabBarSurfacePropsV2 {
  readonly input: DesktopWorkbenchTabBarInputV2;
}

export function DesktopWorkbenchTabBarSurfaceV2({
  input,
}: DesktopWorkbenchTabBarSurfacePropsV2) {
  return <WorkbenchTabBar {...input} />;
}
