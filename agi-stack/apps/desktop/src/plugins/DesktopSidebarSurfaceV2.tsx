import type { ComponentProps } from 'react';

import { ResizeHandle } from '../components/ResizeHandle';
import { DesktopSidebar } from '../features/navigation/DesktopSidebar';

export type DesktopSidebarResizeHandleV2 =
  | Readonly<{ kind: 'hidden' }>
  | Readonly<{
      kind: 'visible';
      props: Readonly<ComponentProps<typeof ResizeHandle>>;
    }>;

export interface DesktopSidebarInputV2 {
  readonly props: Omit<ComponentProps<typeof DesktopSidebar>, 'resizeHandle'>;
  readonly resizeHandle: DesktopSidebarResizeHandleV2;
}

export interface DesktopSidebarSurfacePropsV2 {
  readonly input: DesktopSidebarInputV2;
}

export function DesktopSidebarSurfaceV2({ input }: DesktopSidebarSurfacePropsV2) {
  const resizeHandle =
    input.resizeHandle.kind === 'visible' ? (
      <ResizeHandle {...input.resizeHandle.props} />
    ) : undefined;
  return <DesktopSidebar {...input.props} resizeHandle={resizeHandle} />;
}
