import { useI18n } from '../i18n';
import type { DesktopSidebarInputV2 } from './DesktopSidebarSurfaceV2';
import {
  projectDesktopSidebarCompositionV2,
  type DesktopRendererSidebarCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export interface DesktopRendererSidebarV2Props {
  readonly input: DesktopSidebarInputV2;
}

export function DesktopRendererSidebarV2({ input }: DesktopRendererSidebarV2Props) {
  const { composition, state } = useDesktopRendererGenerationV2();
  const sidebar = projectDesktopSidebarCompositionV2(state.authority, composition);
  if (sidebar.status === 'ready') {
    const Surface = sidebar.Surface;
    return <Surface input={input} />;
  }
  return <DesktopRendererSidebarBoundaryV2 composition={sidebar} />;
}

function DesktopRendererSidebarBoundaryV2({
  composition,
}: Readonly<{
  composition: Exclude<DesktopRendererSidebarCompositionV2, Readonly<{ status: 'ready' }>>;
}>) {
  const { t } = useI18n();
  const loading = composition.status === 'loading';
  return (
    <aside
      className="desktop-design-sidebar"
      data-sidebar-state={composition.status}
      data-reason-code={loading ? undefined : composition.reasonCode}
      role={loading ? 'status' : 'alert'}
      aria-live="polite"
    >
      <span>
        {t(
          loading
            ? 'desktopProductionRouter.loading.description'
            : 'desktopProductionRouter.unavailable.description',
        )}
      </span>
    </aside>
  );
}
