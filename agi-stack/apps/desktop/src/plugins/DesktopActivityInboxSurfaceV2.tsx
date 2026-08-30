import type { ComponentProps } from 'react';

import { ActivityInbox } from '../features/activity/ActivityInbox';

export type DesktopActivityInboxInputV2 = Readonly<ComponentProps<typeof ActivityInbox>>;

export interface DesktopActivityInboxSurfacePropsV2 {
  readonly input: DesktopActivityInboxInputV2;
}

export function DesktopActivityInboxSurfaceV2({ input }: DesktopActivityInboxSurfacePropsV2) {
  return <ActivityInbox {...input} />;
}
