import { useI18n } from '../i18n';
import type { DesktopConversationInputV2 } from './DesktopConversationSurfaceV2';
import {
  projectDesktopConversationCompositionV2,
  type DesktopRendererConversationCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export interface DesktopRendererConversationV2Props {
  readonly input: DesktopConversationInputV2;
}

export function DesktopRendererConversationV2({ input }: DesktopRendererConversationV2Props) {
  const { composition, state } = useDesktopRendererGenerationV2();
  const conversation = projectDesktopConversationCompositionV2(state.authority, composition);
  if (conversation.status === 'ready') {
    const Surface = conversation.Surface;
    return <Surface input={input} />;
  }
  return <DesktopRendererConversationBoundaryV2 composition={conversation} />;
}

function DesktopRendererConversationBoundaryV2({
  composition,
}: Readonly<{
  composition: Exclude<DesktopRendererConversationCompositionV2, Readonly<{ status: 'ready' }>>;
}>) {
  const { t } = useI18n();
  const loading = composition.status === 'loading';
  return (
    <section
      className="desktop-production-route-boundary"
      data-conversation-state={composition.status}
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
