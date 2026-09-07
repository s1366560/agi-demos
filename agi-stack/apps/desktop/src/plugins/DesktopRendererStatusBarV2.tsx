import { useI18n } from '../i18n';
import type { DesktopStatusBarInputV2 } from './DesktopStatusBarSurfaceV2';
import {
  projectDesktopStatusBarCompositionV2,
  type DesktopRendererStatusBarCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export interface DesktopRendererStatusBarV2Props {
  readonly input: DesktopStatusBarInputV2;
}

export function DesktopRendererStatusBarV2({ input }: DesktopRendererStatusBarV2Props) {
  const { composition, state } = useDesktopRendererGenerationV2();
  const statusBar = projectDesktopStatusBarCompositionV2(state.authority, composition);
  if (statusBar.status === 'ready') {
    const Surface = statusBar.Surface;
    return <Surface input={input} />;
  }
  return <DesktopRendererStatusBarBoundaryV2 composition={statusBar} />;
}

function DesktopRendererStatusBarBoundaryV2({
  composition,
}: Readonly<{
  composition: Exclude<DesktopRendererStatusBarCompositionV2, Readonly<{ status: 'ready' }>>;
}>) {
  const { t } = useI18n();
  const loading = composition.status === 'loading';
  return (
    <footer
      className="desktop-status-bar"
      data-status-bar-state={composition.status}
      data-reason-code={loading ? undefined : composition.reasonCode}
      role={loading ? 'status' : 'alert'}
      aria-live="polite"
    >
      <span
        className="desktop-status-bar-segment"
        data-tone={loading ? 'idle' : 'error'}
      >
        {t(
          loading
            ? 'desktopProductionRouter.loading.description'
            : 'desktopProductionRouter.unavailable.description',
        )}
      </span>
    </footer>
  );
}
