import type { ComponentProps } from 'react';

import { MyWorkQueue } from '../features/my-work/MyWorkQueue';

export type DesktopMyWorkQueueInputV2 = Readonly<ComponentProps<typeof MyWorkQueue>>;

export interface DesktopMyWorkQueueSurfacePropsV2 {
  readonly input: DesktopMyWorkQueueInputV2;
}

export function DesktopMyWorkQueueSurfaceV2({ input }: DesktopMyWorkQueueSurfacePropsV2) {
  return <MyWorkQueue {...input} />;
}
