import { useI18n } from '../i18n';
import type { DesktopAuthenticatedShellViewModelV2 } from './DesktopAuthenticatedShellSurfaceV2';
import {
  projectDesktopAuthenticatedShellCompositionV2,
  type DesktopRendererAuthenticatedShellCompositionV2,
} from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';
import { isDesktopRendererCredentialRequiredV2 } from './desktopRendererDeliveryStatusV2';

export interface DesktopRendererAuthenticatedShellV2Props {
  readonly viewModel: DesktopAuthenticatedShellViewModelV2;
}

export function DesktopRendererAuthenticatedShellV2({
  viewModel,
}: DesktopRendererAuthenticatedShellV2Props) {
  const { composition, state } = useDesktopRendererGenerationV2();
  const shell = projectDesktopAuthenticatedShellCompositionV2(state.authority, composition);
  if (shell.status === 'ready') {
    const Surface = shell.Surface;
    return <Surface viewModel={viewModel} />;
  }
  return (
    <DesktopRendererAuthenticatedShellBoundaryV2
      composition={shell}
      credentialRequired={isDesktopRendererCredentialRequiredV2(state.authority.error)}
      onSignOut={viewModel.surfaces.settings.onSignOut}
    />
  );
}

function DesktopRendererAuthenticatedShellBoundaryV2({
  composition,
  credentialRequired,
  onSignOut,
}: Readonly<{
  composition: Exclude<
    DesktopRendererAuthenticatedShellCompositionV2,
    Readonly<{ status: 'ready' }>
  >;
  credentialRequired: boolean;
  onSignOut: () => void | Promise<void>;
}>) {
  const { t } = useI18n();
  const loading = composition.status === 'loading';
  return (
    <section
      className="desktop-production-route-boundary"
      data-authenticated-shell-state={composition.status}
      data-reason-code={loading ? undefined : composition.reasonCode}
      data-cause-code={!loading && credentialRequired ? 'renderer_credential_required' : undefined}
      role={loading ? 'status' : 'alert'}
      aria-live="polite"
    >
      <h1>
        {t(
          loading
            ? 'desktopProductionRouter.loading.title'
            : credentialRequired
              ? 'desktopProductionRouter.credentialRequired.title'
              : 'desktopProductionRouter.unavailable.title',
        )}
      </h1>
      <p>
        {t(
          loading
            ? 'desktopProductionRouter.loading.description'
            : credentialRequired
              ? 'desktopProductionRouter.credentialRequired.description'
              : 'desktopProductionRouter.unavailable.description',
        )}
      </p>
      {!loading ? (
        <button type="button" data-action="sign-out" onClick={() => void onSignOut()}>
          {t(credentialRequired
            ? 'desktopProductionRouter.credentialRequired.signOut'
            : 'settings.signOut')}
        </button>
      ) : null}
    </section>
  );
}
