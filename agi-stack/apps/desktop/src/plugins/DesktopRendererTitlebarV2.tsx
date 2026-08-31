import { useI18n } from '../i18n';
import type { DesktopTitlebarInputV2 } from './DesktopTitlebarSurfaceV2';
import {
  projectDesktopTitlebarCompositionV2,
  type DesktopRendererTitlebarCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export interface DesktopRendererTitlebarV2Props {
  readonly input: DesktopTitlebarInputV2;
}

export function DesktopRendererTitlebarV2({ input }: DesktopRendererTitlebarV2Props) {
  const { composition, state } = useDesktopRendererGenerationV2();
  const titlebar = projectDesktopTitlebarCompositionV2(state.authority, composition);
  if (titlebar.status === 'ready') {
    const Surface = titlebar.Surface;
    return <Surface input={input} />;
  }
  if (input.kind === 'hidden') return null;
  return <DesktopRendererTitlebarBoundaryV2 composition={titlebar} />;
}

function DesktopRendererTitlebarBoundaryV2({
  composition,
}: Readonly<{
  composition: Exclude<DesktopRendererTitlebarCompositionV2, Readonly<{ status: 'ready' }>>;
}>) {
  const { t } = useI18n();
  const loading = composition.status === 'loading';
  const platform = window.__MEMSTACK_DESKTOP__?.platform ?? 'darwin';
  return (
    <header
      className="desktop-titlebar"
      data-titlebar-state={composition.status}
      data-reason-code={loading ? undefined : composition.reasonCode}
      role={loading ? 'status' : 'alert'}
      aria-live="polite"
    >
      {platform === 'darwin' ? (
        <div className="desktop-titlebar-traffic-pad" aria-hidden="true" />
      ) : null}
      <span className="desktop-titlebar-title">
        {t(
          loading
            ? 'desktopProductionRouter.loading.description'
            : 'desktopProductionRouter.unavailable.description',
        )}
      </span>
    </header>
  );
}
