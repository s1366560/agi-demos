import { useI18n } from '../i18n';
import type { DesktopSettingsWindowInputV2 } from './DesktopSettingsWindowSurfaceV2';
import {
  projectDesktopSettingsWindowCompositionV2,
  type DesktopRendererSettingsWindowCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export interface DesktopRendererSettingsWindowV2Props {
  readonly input: DesktopSettingsWindowInputV2;
}

export function DesktopRendererSettingsWindowV2({ input }: DesktopRendererSettingsWindowV2Props) {
  const { composition, state } = useDesktopRendererGenerationV2();
  const settingsWindow = projectDesktopSettingsWindowCompositionV2(
    state.authority,
    composition,
  );
  if (settingsWindow.status === 'ready') {
    const Surface = settingsWindow.Surface;
    return <Surface input={input} />;
  }
  if (!input.open) return null;
  return <DesktopRendererSettingsWindowBoundaryV2 composition={settingsWindow} />;
}

function DesktopRendererSettingsWindowBoundaryV2({
  composition,
}: Readonly<{
  composition: Exclude<
    DesktopRendererSettingsWindowCompositionV2,
    Readonly<{ status: 'ready' }>
  >;
}>) {
  const { t } = useI18n();
  const loading = composition.status === 'loading';
  return (
    <section
      className="desktop-production-route-boundary"
      data-settings-window-state={composition.status}
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
