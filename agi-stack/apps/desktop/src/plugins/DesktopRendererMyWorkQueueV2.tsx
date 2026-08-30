import { useI18n } from '../i18n';
import type { DesktopMyWorkQueueInputV2 } from './DesktopMyWorkQueueSurfaceV2';
import {
  projectDesktopMyWorkQueueCompositionV2,
  type DesktopRendererMyWorkQueueCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export interface DesktopRendererMyWorkQueueV2Props {
  readonly input: DesktopMyWorkQueueInputV2;
}

export function DesktopRendererMyWorkQueueV2({ input }: DesktopRendererMyWorkQueueV2Props) {
  const { composition, state } = useDesktopRendererGenerationV2();
  const myWorkQueue = projectDesktopMyWorkQueueCompositionV2(state.authority, composition);
  if (myWorkQueue.status === 'ready') {
    const Surface = myWorkQueue.Surface;
    return <Surface input={input} />;
  }
  return <DesktopRendererMyWorkQueueBoundaryV2 composition={myWorkQueue} />;
}

function DesktopRendererMyWorkQueueBoundaryV2({
  composition,
}: Readonly<{
  composition: Exclude<DesktopRendererMyWorkQueueCompositionV2, Readonly<{ status: 'ready' }>>;
}>) {
  const { t } = useI18n();
  const loading = composition.status === 'loading';
  return (
    <section
      className="desktop-production-route-boundary"
      data-my-work-queue-state={composition.status}
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
