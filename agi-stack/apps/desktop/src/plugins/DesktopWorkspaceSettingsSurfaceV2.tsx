import type { ComponentProps } from 'react';

import { WorkspaceSettingsDialog } from '../features/workspace/WorkspaceSettingsDialog';

export type DesktopWorkspaceSettingsInputV2 = Readonly<
  ComponentProps<typeof WorkspaceSettingsDialog>
>;

export interface DesktopWorkspaceSettingsSurfacePropsV2 {
  readonly input: DesktopWorkspaceSettingsInputV2;
}

export function DesktopWorkspaceSettingsSurfaceV2({
  input,
}: DesktopWorkspaceSettingsSurfacePropsV2) {
  return <WorkspaceSettingsDialog {...input} />;
}
