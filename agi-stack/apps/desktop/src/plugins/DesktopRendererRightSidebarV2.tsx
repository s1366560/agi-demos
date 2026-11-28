import { useI18n } from '../i18n';
import type { DesktopRightSidebarInputV2 } from './DesktopRightSidebarSurfaceV2';
import {
  projectDesktopRightSidebarCompositionV2,
  type DesktopRendererRightSidebarCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export interface DesktopRendererRightSidebarV2Props {
  readonly input: DesktopRightSidebarInputV2;
}

export function DesktopRendererRightSidebarV2({ input }: DesktopRendererRightSidebarV2Props) {
  const { composition, state } = useDesktopRendererGenerationV2();
  const rightSidebar = projectDesktopRightSidebarCompositionV2(state.authority, composition);
  if (rightSidebar.status === 'ready') {
    const Surface = rightSidebar.Surface;
    return <Surface input={input} />;
  }
  return <DesktopRendererRightSidebarBoundaryV2 composition={rightSidebar} />;
}

function DesktopRendererRightSidebarBoundaryV2({
  composition,
}: Readonly<{
  composition: Exclude<
    DesktopRendererRightSidebarCompositionV2,
    Readonly<{ status: 'ready' }>
  >;
}>) {
  const { t } = useI18n();
  const loading = composition.status === 'loading';
  return (
    <aside
      className="desktop-right-sidebar"
      data-right-sidebar-state={composition.status}
      data-reason-code={loading ? undefined : composition.reasonCode}
      style={{ width: 320 }}
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
