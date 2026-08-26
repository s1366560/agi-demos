import type { ReactNode } from 'react';

import { useTranslation } from 'react-i18next';
import { Outlet } from 'react-router-dom';

import { WebRoutePageLoaderV2 } from '../routes/v2/WebRoutePageLoaderV2';
import { useWebUiSlotAuthorityV2 } from '../routes/v2/webUiSlotAuthorityStateV2';

import {
  projectWebAuthenticatedShellCompositionV2,
  type WebRendererAuthenticatedShellCompositionV2,
  useCurrentWebRendererCompositionV2,
} from './webRendererCompositionPortV2';

export interface WebRendererAuthenticatedShellV2Props {
  readonly children?: ReactNode;
}

export function WebRendererAuthenticatedShellV2({
  children,
}: WebRendererAuthenticatedShellV2Props) {
  const authority = useWebUiSlotAuthorityV2();
  const composition = useCurrentWebRendererCompositionV2();
  const shell = projectWebAuthenticatedShellCompositionV2(authority, composition);
  if (shell.status === 'ready') {
    const Surface = shell.Surface;
    return <Surface>{children ?? <Outlet />}</Surface>;
  }
  return <WebRendererAuthenticatedShellBoundaryV2 composition={shell} />;
}

function WebRendererAuthenticatedShellBoundaryV2({
  composition,
}: Readonly<{
  composition: Exclude<WebRendererAuthenticatedShellCompositionV2, Readonly<{ status: 'ready' }>>;
}>) {
  const { t } = useTranslation();
  if (composition.status === 'loading') return <WebRoutePageLoaderV2 />;
  return (
    <section
      className="flex min-h-50 flex-col items-center justify-center gap-2 p-6 text-center"
      data-authenticated-shell-state={composition.status}
      data-reason-code={composition.reasonCode}
      role="alert"
      aria-live="polite"
    >
      <h1 className="text-lg font-semibold">{t('error.title')}</h1>
      <p className="text-sm text-text-secondary">{t('error.subtitle')}</p>
    </section>
  );
}
