import type { ReactNode } from 'react';

import { useI18n } from '../i18n';
import type { DesktopSessionWorkspaceInputV2 } from './DesktopSessionWorkspaceSurfaceV2';
import {
  projectDesktopSessionWorkspaceCompositionV2,
  type DesktopRendererSessionWorkspaceCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export interface DesktopRendererSessionWorkspaceV2Props {
  readonly input: DesktopSessionWorkspaceInputV2;
  readonly thread: ReactNode;
}

export function DesktopRendererSessionWorkspaceV2({
  input,
  thread,
}: DesktopRendererSessionWorkspaceV2Props) {
  const { composition, state } = useDesktopRendererGenerationV2();
  const sessionWorkspace = projectDesktopSessionWorkspaceCompositionV2(
    state.authority,
    composition,
  );
  if (sessionWorkspace.status === 'ready') {
    const Surface = sessionWorkspace.Surface;
    return <Surface input={input} thread={thread} />;
  }
  return <DesktopRendererSessionWorkspaceBoundaryV2 composition={sessionWorkspace} />;
}

function DesktopRendererSessionWorkspaceBoundaryV2({
  composition,
}: Readonly<{
  composition: Exclude<
    DesktopRendererSessionWorkspaceCompositionV2,
    Readonly<{ status: 'ready' }>
  >;
}>) {
  const { t } = useI18n();
  const loading = composition.status === 'loading';
  return (
    <section
      className="desktop-production-route-boundary"
      data-session-workspace-state={composition.status}
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
