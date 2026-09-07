import type { ComponentProps } from 'react';

import { DesktopTitlebar } from '../features/chrome/DesktopTitlebar';

export type DesktopTitlebarInputV2 =
  | Readonly<{ kind: 'hidden' }>
  | Readonly<{
      kind: 'visible';
      props: Readonly<ComponentProps<typeof DesktopTitlebar>>;
    }>;

export interface DesktopTitlebarSurfacePropsV2 {
  readonly input: DesktopTitlebarInputV2;
}

export function DesktopTitlebarSurfaceV2({ input }: DesktopTitlebarSurfacePropsV2) {
  if (input.kind === 'hidden') return null;
  return <DesktopTitlebar {...input.props} />;
}
