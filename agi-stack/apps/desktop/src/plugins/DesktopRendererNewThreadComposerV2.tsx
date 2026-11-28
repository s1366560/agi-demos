import { useI18n } from '../i18n';
import type { DesktopNewThreadComposerInputV2 } from './DesktopNewThreadComposerSurfaceV2';
import {
  projectDesktopNewThreadComposerCompositionV2,
  type DesktopRendererNewThreadComposerCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export interface DesktopRendererNewThreadComposerV2Props {
  readonly input: DesktopNewThreadComposerInputV2;
}

export function DesktopRendererNewThreadComposerV2({
  input,
}: DesktopRendererNewThreadComposerV2Props) {
  const { composition, state } = useDesktopRendererGenerationV2();
  const newThreadComposer = projectDesktopNewThreadComposerCompositionV2(
    state.authority,
    composition,
  );
  if (newThreadComposer.status === 'ready') {
    const Surface = newThreadComposer.Surface;
    return <Surface input={input} />;
  }
  return <DesktopRendererNewThreadComposerBoundaryV2 composition={newThreadComposer} />;
}

function DesktopRendererNewThreadComposerBoundaryV2({
  composition,
}: Readonly<{
  composition: Exclude<
    DesktopRendererNewThreadComposerCompositionV2,
    Readonly<{ status: 'ready' }>
  >;
}>) {
  const { t } = useI18n();
  const loading = composition.status === 'loading';
  return (
    <section
      className="desktop-production-route-boundary"
      data-new-thread-composer-state={composition.status}
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
