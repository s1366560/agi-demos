import { Fragment } from 'react';

import type { WebRendererAuthenticatedShellSurfacePropsV2 } from './webRendererCompositionPortV2';

export function WebAuthenticatedShellSurfaceV2({
  children,
}: WebRendererAuthenticatedShellSurfacePropsV2) {
  return <Fragment>{children}</Fragment>;
}
