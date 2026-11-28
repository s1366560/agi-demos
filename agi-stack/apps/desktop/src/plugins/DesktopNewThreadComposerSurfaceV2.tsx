import type { ComponentProps } from 'react';

import { NewThreadComposer } from '../features/task/NewThreadComposer';

export type DesktopNewThreadComposerInputV2 = Readonly<{
  scopeKey: string;
  composer: Readonly<ComponentProps<typeof NewThreadComposer>>;
}>;

export interface DesktopNewThreadComposerSurfacePropsV2 {
  readonly input: DesktopNewThreadComposerInputV2;
}

export function DesktopNewThreadComposerSurfaceV2({
  input,
}: DesktopNewThreadComposerSurfacePropsV2) {
  return <NewThreadComposer key={input.scopeKey} {...input.composer} />;
}
