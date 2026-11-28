import type { ComponentProps } from 'react';

import { NewTaskFlow } from '@business/agent/ui/desktop/task/NewTaskFlow';

export type DesktopNewTaskFlowInputV2 = Readonly<ComponentProps<typeof NewTaskFlow>>;

export interface DesktopNewTaskFlowSurfacePropsV2 {
  readonly input: DesktopNewTaskFlowInputV2;
}

export function DesktopNewTaskFlowSurfaceV2({ input }: DesktopNewTaskFlowSurfacePropsV2) {
  return <NewTaskFlow {...input} />;
}
