import type { ComponentProps } from 'react';

import { DesktopRightSidebar } from '../features/chrome/DesktopRightSidebar';

export type DesktopRightSidebarInputV2 = Readonly<ComponentProps<typeof DesktopRightSidebar>>;

export interface DesktopRightSidebarSurfacePropsV2 {
  readonly input: DesktopRightSidebarInputV2;
}

export function DesktopRightSidebarSurfaceV2({ input }: DesktopRightSidebarSurfacePropsV2) {
  return <DesktopRightSidebar {...input} />;
}
