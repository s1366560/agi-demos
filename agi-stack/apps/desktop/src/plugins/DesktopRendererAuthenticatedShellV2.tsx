import type { ReactNode } from 'react';

import { useI18n } from '../i18n';
import {
  projectDesktopAuthenticatedShellCompositionV2,
  type DesktopRendererAuthenticatedShellCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export interface DesktopRendererAuthenticatedShellV2Props {
  readonly children: ReactNode;
}

export function DesktopRendererAuthenticatedShellV2({
  children,
}: DesktopRendererAuthenticatedShellV2Props) {
  const { composition, state } = useDesktopRendererGenerationV2();
  const shell = projectDesktopAuthenticatedShellCompositionV2(state.authority, composition);
  if (shell.status === 'ready') {
    const Surface = shell.Surface;
    return <Surface>{children}</Surface>;
  }
  return <DesktopRendererAuthenticatedShellBoundaryV2 composition={shell} />;
}

function DesktopRendererAuthenticatedShellBoundaryV2({
  composition,
}: Readonly<{
  composition: Exclude<
    DesktopRendererAuthenticatedShellCompositionV2,
    Readonly<{ status: 'ready' }>
  >;
}>) {
  const { t } = useI18n();
  const loading = composition.status === 'loading';
  return (
    <section
      className="desktop-production-route-boundary"
      data-authenticated-shell-state={composition.status}
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
