import { createPortal } from 'react-dom';

import { useI18n } from '../i18n';
import type { DesktopNewTaskFlowInputV2 } from './DesktopNewTaskFlowSurfaceV2';
import {
  projectDesktopNewTaskFlowCompositionV2,
  type DesktopRendererNewTaskFlowCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export interface DesktopRendererNewTaskFlowV2Props {
  readonly input: DesktopNewTaskFlowInputV2;
}

export function DesktopRendererNewTaskFlowV2({ input }: DesktopRendererNewTaskFlowV2Props) {
  const { composition, state } = useDesktopRendererGenerationV2();
  const newTaskFlow = projectDesktopNewTaskFlowCompositionV2(state.authority, composition);
  if (newTaskFlow.status === 'ready') {
    const Surface = newTaskFlow.Surface;
    return <Surface input={input} />;
  }
  if (!input.open) return null;
  return <DesktopRendererNewTaskFlowBoundaryV2 composition={newTaskFlow} input={input} />;
}

function DesktopRendererNewTaskFlowBoundaryV2({
  composition,
  input,
}: Readonly<{
  composition: Exclude<DesktopRendererNewTaskFlowCompositionV2, Readonly<{ status: 'ready' }>>;
  input: DesktopNewTaskFlowInputV2;
}>) {
  const { t } = useI18n();
  const loading = composition.status === 'loading';
  return createPortal(
    <div
      className="new-task-backdrop"
      data-new-task-flow-state={composition.status}
      data-reason-code={loading ? undefined : composition.reasonCode}
      role={loading ? 'status' : 'alert'}
      aria-live="polite"
    >
      <section className="desktop-production-route-boundary">
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
        <button type="button" onClick={input.onClose}>
          {t('common.close')}
        </button>
      </section>
    </div>,
    document.body,
  );
}
