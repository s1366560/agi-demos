import type { ComponentProps, ReactNode } from 'react';

import { SessionWorkspace } from '../features/session/SessionWorkspace';

export type DesktopSessionWorkspaceInputV2 = Readonly<
  Omit<ComponentProps<typeof SessionWorkspace>, 'thread'>
>;

export interface DesktopSessionWorkspaceSurfacePropsV2 {
  readonly input: DesktopSessionWorkspaceInputV2;
  readonly thread: ReactNode;
}

export function DesktopSessionWorkspaceSurfaceV2({
  input,
  thread,
}: DesktopSessionWorkspaceSurfacePropsV2) {
  return <SessionWorkspace {...input} thread={thread} />;
}
