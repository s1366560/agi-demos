import { useI18n } from '../i18n';
import type { DesktopWorkspaceCollaborationInputV2 } from './DesktopWorkspaceCollaborationSurfaceV2';
import {
  projectDesktopWorkspaceCollaborationCompositionV2,
  type DesktopRendererWorkspaceCollaborationCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export interface DesktopRendererWorkspaceCollaborationV2Props {
  readonly input: DesktopWorkspaceCollaborationInputV2;
}

export function DesktopRendererWorkspaceCollaborationV2({
  input,
}: DesktopRendererWorkspaceCollaborationV2Props) {
  const { composition, state } = useDesktopRendererGenerationV2();
  const workspaceCollaboration = projectDesktopWorkspaceCollaborationCompositionV2(
    state.authority,
    composition,
  );
  if (workspaceCollaboration.status === 'ready') {
    const Surface = workspaceCollaboration.Surface;
    return <Surface input={input} />;
  }
  return <DesktopRendererWorkspaceCollaborationBoundaryV2 composition={workspaceCollaboration} />;
}

function DesktopRendererWorkspaceCollaborationBoundaryV2({
  composition,
}: Readonly<{
  composition: Exclude<
    DesktopRendererWorkspaceCollaborationCompositionV2,
    Readonly<{ status: 'ready' }>
  >;
}>) {
  const { t } = useI18n();
  const loading = composition.status === 'loading';
  return (
    <section
      className="desktop-production-route-boundary"
      data-workspace-collaboration-state={composition.status}
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
