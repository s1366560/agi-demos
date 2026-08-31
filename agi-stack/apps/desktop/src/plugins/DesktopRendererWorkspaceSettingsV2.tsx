import { useI18n } from '../i18n';
import type { DesktopWorkspaceSettingsInputV2 } from './DesktopWorkspaceSettingsSurfaceV2';
import {
  projectDesktopWorkspaceSettingsCompositionV2,
  type DesktopRendererWorkspaceSettingsCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export interface DesktopRendererWorkspaceSettingsV2Props {
  readonly input: DesktopWorkspaceSettingsInputV2;
}

export function DesktopRendererWorkspaceSettingsV2({
  input,
}: DesktopRendererWorkspaceSettingsV2Props) {
  const { composition, state } = useDesktopRendererGenerationV2();
  const workspaceSettings = projectDesktopWorkspaceSettingsCompositionV2(
    state.authority,
    composition,
  );
  if (workspaceSettings.status === 'ready') {
    const Surface = workspaceSettings.Surface;
    return <Surface input={input} />;
  }
  if (!input.open) return null;
  return <DesktopRendererWorkspaceSettingsBoundaryV2 composition={workspaceSettings} />;
}

function DesktopRendererWorkspaceSettingsBoundaryV2({
  composition,
}: Readonly<{
  composition: Exclude<
    DesktopRendererWorkspaceSettingsCompositionV2,
    Readonly<{ status: 'ready' }>
  >;
}>) {
  const { t } = useI18n();
  const loading = composition.status === 'loading';
  return (
    <section
      className="desktop-production-route-boundary"
      data-workspace-settings-state={composition.status}
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
