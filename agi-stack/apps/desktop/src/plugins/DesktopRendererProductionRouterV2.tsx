import {
  DesktopProductionRouter,
  type DesktopProductionRouterProps,
} from '../features/navigation/DesktopProductionRouter';
import { useI18n } from '../i18n';
import {
  projectDesktopWorkbenchCompositionV2,
  type DesktopRendererWorkbenchCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export type DesktopRendererProductionRouterV2Props = Omit<
  DesktopProductionRouterProps,
  'acquireOperationLease' | 'registry'
> &
  Readonly<{
    childrenAuthority?: 'authentication-kernel' | 'workbench-contribution';
  }>;

export function DesktopRendererProductionRouterV2({
  children,
  childrenAuthority = 'workbench-contribution',
  ...props
}: DesktopRendererProductionRouterV2Props) {
  const { actions, composition, state } = useDesktopRendererGenerationV2();
  const workbench =
    childrenAuthority === 'authentication-kernel'
      ? null
      : projectDesktopWorkbenchCompositionV2(state.authority, composition);
  return (
    <DesktopProductionRouter
      {...props}
      acquireOperationLease={actions.acquireOperationLease}
      registry={state.routeRegistry}
    >
      {workbench === null ? children : renderWorkbenchCompositionV2(workbench, children)}
    </DesktopProductionRouter>
  );
}

function renderWorkbenchCompositionV2(
  composition: DesktopRendererWorkbenchCompositionV2,
  children: DesktopProductionRouterProps['children'],
) {
  if (composition.status === 'ready') {
    const Surface = composition.Surface;
    return <Surface>{children}</Surface>;
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
