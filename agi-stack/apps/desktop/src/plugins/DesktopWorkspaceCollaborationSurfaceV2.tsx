import type { ComponentProps } from 'react';

import { WorkspaceCollaborationCanvas } from '../features/workspace/WorkspaceCollaborationCanvas';

export type DesktopWorkspaceCollaborationInputV2 = Readonly<
  ComponentProps<typeof WorkspaceCollaborationCanvas>
>;

export interface DesktopWorkspaceCollaborationSurfacePropsV2 {
  readonly input: DesktopWorkspaceCollaborationInputV2;
}

export function DesktopWorkspaceCollaborationSurfaceV2({
  input,
}: DesktopWorkspaceCollaborationSurfacePropsV2) {
  return <WorkspaceCollaborationCanvas {...input} />;
}
