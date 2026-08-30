import { useI18n } from '../i18n';
import type { DesktopActivityInboxInputV2 } from './DesktopActivityInboxSurfaceV2';
import {
  projectDesktopActivityInboxCompositionV2,
  type DesktopRendererActivityInboxCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export interface DesktopRendererActivityInboxV2Props {
  readonly input: DesktopActivityInboxInputV2;
}

export function DesktopRendererActivityInboxV2({ input }: DesktopRendererActivityInboxV2Props) {
  const { composition, state } = useDesktopRendererGenerationV2();
  const activityInbox = projectDesktopActivityInboxCompositionV2(state.authority, composition);
  if (activityInbox.status === 'ready') {
    const Surface = activityInbox.Surface;
    return <Surface input={input} />;
  }
  return <DesktopRendererActivityInboxBoundaryV2 composition={activityInbox} />;
}

function DesktopRendererActivityInboxBoundaryV2({
  composition,
}: Readonly<{
  composition: Exclude<DesktopRendererActivityInboxCompositionV2, Readonly<{ status: 'ready' }>>;
}>) {
  const { t } = useI18n();
  const loading = composition.status === 'loading';
  return (
    <section
      className="desktop-production-route-boundary"
      data-activity-inbox-state={composition.status}
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
