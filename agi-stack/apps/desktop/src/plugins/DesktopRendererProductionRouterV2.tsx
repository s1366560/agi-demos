import {
  DesktopProductionRouter,
  type DesktopProductionRouterProps,
} from '../features/navigation/DesktopProductionRouter';
import { useI18n } from '../i18n';
import type { DesktopWorkbenchSurfaceViewModelV2 } from './DesktopWorkbenchSurfaceV2';
import {
  projectDesktopWorkbenchCompositionV2,
  type DesktopRendererWorkbenchCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export type DesktopRendererProductionRouterV2Props = Omit<
  DesktopProductionRouterProps,
  'acquireOperationLease' | 'children' | 'registry'
> &
  Readonly<{
    readonly viewModel: DesktopWorkbenchSurfaceViewModelV2;
  }>;

export function DesktopRendererProductionRouterV2({
  viewModel,
  ...props
}: DesktopRendererProductionRouterV2Props) {
  const { actions, composition, state } = useDesktopRendererGenerationV2();
  const workbench = projectDesktopWorkbenchCompositionV2(state.authority, composition);
  return (
    <DesktopProductionRouter
      {...props}
      acquireOperationLease={actions.acquireOperationLease}
      registry={state.routeRegistry}
    >
      {renderWorkbenchCompositionV2(workbench, viewModel)}
    </DesktopProductionRouter>
  );
}

function renderWorkbenchCompositionV2(
  composition: DesktopRendererWorkbenchCompositionV2,
  viewModel: DesktopWorkbenchSurfaceViewModelV2,
) {
  if (composition.status === 'ready') {
    const Surface = composition.Surface;
    return <Surface viewModel={viewModel} />;
  }
  return <DesktopRendererWorkbenchBoundaryV2 composition={composition} />;
}

function DesktopRendererWorkbenchBoundaryV2({
  composition,
}: Readonly<{
  composition: Exclude<DesktopRendererWorkbenchCompositionV2, Readonly<{ status: 'ready' }>>;
}>) {
  const { t } = useI18n();
  const loading = composition.status === 'loading';
  return (
    <section
      className="desktop-production-route-boundary"
      data-reason-code={loading ? undefined : composition.reasonCode}
      data-route-state={composition.status}
      role={loading ? 'status' : 'alert'}
      aria-live="polite"
    >
      <h1>
        {t(
          loading
            ? 'desktopProductionRouter.loading.title'
            : 'desktopProductionRouter.unavailable.title',
        )}
      </h1>
      <p>
        {t(
          loading
            ? 'desktopProductionRouter.loading.description'
            : 'desktopProductionRouter.unavailable.description',
        )}
      </p>
    </section>
  );
}
