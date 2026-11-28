import { useI18n } from '../i18n';
import type { DesktopWorkspaceCreateInputV2 } from './DesktopWorkspaceCreateSurfaceV2';
import {
  projectDesktopWorkspaceCreateCompositionV2,
  type DesktopRendererWorkspaceCreateCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export interface DesktopRendererWorkspaceCreateV2Props {
  readonly input: DesktopWorkspaceCreateInputV2;
}

export function DesktopRendererWorkspaceCreateV2({ input }: DesktopRendererWorkspaceCreateV2Props) {
  const { composition, state } = useDesktopRendererGenerationV2();
  const workspaceCreate = projectDesktopWorkspaceCreateCompositionV2(state.authority, composition);
  if (workspaceCreate.status === 'ready') {
    const Surface = workspaceCreate.Surface;
    return <Surface input={input} />;
  }
  if (!input.open) return null;
  return <DesktopRendererWorkspaceCreateBoundaryV2 composition={workspaceCreate} />;
}

function DesktopRendererWorkspaceCreateBoundaryV2({
  composition,
}: Readonly<{
  composition: Exclude<DesktopRendererWorkspaceCreateCompositionV2, Readonly<{ status: 'ready' }>>;
}>) {
  const { t } = useI18n();
  const loading = composition.status === 'loading';
  return (
    <section
      className="desktop-production-route-boundary"
      data-workspace-create-state={composition.status}
      data-reason-code={loading ? undefined : composition.reasonCode}
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
