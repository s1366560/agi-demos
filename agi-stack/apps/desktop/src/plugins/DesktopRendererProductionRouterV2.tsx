import {
  DesktopProductionRouter,
  type DesktopProductionRouterProps,
} from '../features/navigation/DesktopProductionRouter';
import { useDesktopRendererGenerationV2 } from './DesktopRendererGenerationHostV2';

export type DesktopRendererProductionRouterV2Props = Omit<
  DesktopProductionRouterProps,
  'acquireOperationLease' | 'registry'
>;

export function DesktopRendererProductionRouterV2(props: DesktopRendererProductionRouterV2Props) {
  const { actions, state } = useDesktopRendererGenerationV2();
  return (
    <DesktopProductionRouter
      {...props}
      acquireOperationLease={actions.acquireOperationLease}
      registry={state.routeRegistry}
    />
  );
}
