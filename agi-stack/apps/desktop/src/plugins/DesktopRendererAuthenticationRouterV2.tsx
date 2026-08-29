import type { ReactNode } from 'react';

import {
  DesktopProductionRouter,
  type DesktopProductionRouterProps,
} from '../features/navigation/DesktopProductionRouter';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export type DesktopRendererAuthenticationRouterV2Props = Omit<
  DesktopProductionRouterProps,
  'acquireOperationLease' | 'children' | 'registry'
> &
  Readonly<{
    readonly children: ReactNode;
  }>;

export function DesktopRendererAuthenticationRouterV2({
  children,
  ...props
}: DesktopRendererAuthenticationRouterV2Props) {
  const { actions, state } = useDesktopRendererGenerationV2();
  return (
    <DesktopProductionRouter
      {...props}
      acquireOperationLease={actions.acquireOperationLease}
      registry={state.routeRegistry}
    >
      {children}
    </DesktopProductionRouter>
  );
}
