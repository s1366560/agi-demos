import type { ComponentProps } from 'react';

import { WorkspaceCreateDialog } from '../features/workspace/WorkspaceCreateDialog';

export type DesktopWorkspaceCreateInputV2 = Readonly<ComponentProps<typeof WorkspaceCreateDialog>>;

export interface DesktopWorkspaceCreateSurfacePropsV2 {
  readonly input: DesktopWorkspaceCreateInputV2;
}

export function DesktopWorkspaceCreateSurfaceV2({ input }: DesktopWorkspaceCreateSurfacePropsV2) {
  return <WorkspaceCreateDialog {...input} />;
}
