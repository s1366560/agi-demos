import type { SessionCanvasControls } from '../features/session/workspaceReviewPanelModel';
import { useI18n } from '../i18n';
import type { DesktopSessionCanvasInputV2 } from './DesktopSessionCanvasSurfaceV2';
import {
  projectDesktopSessionCanvasCompositionV2,
  type DesktopRendererSessionCanvasCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export interface DesktopRendererSessionCanvasV2Props {
  readonly controls: SessionCanvasControls;
  readonly input: DesktopSessionCanvasInputV2;
}

export function DesktopRendererSessionCanvasV2({
  controls,
  input,
}: DesktopRendererSessionCanvasV2Props) {
  const { composition, state } = useDesktopRendererGenerationV2();
  const canvas = projectDesktopSessionCanvasCompositionV2(state.authority, composition);
  if (canvas.status === 'ready') {
    const Surface = canvas.Surface;
    return <Surface input={input} controls={controls} />;
  }
  return <DesktopRendererSessionCanvasBoundaryV2 composition={canvas} />;
}

function DesktopRendererSessionCanvasBoundaryV2({
  composition,
}: Readonly<{
  composition: Exclude<DesktopRendererSessionCanvasCompositionV2, Readonly<{ status: 'ready' }>>;
}>) {
  const { t } = useI18n();
  const loading = composition.status === 'loading';
  return (
    <section
      className="desktop-production-route-boundary"
      data-session-canvas-state={composition.status}
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
