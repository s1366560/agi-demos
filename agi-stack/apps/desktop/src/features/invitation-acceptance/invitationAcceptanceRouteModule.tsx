import { useMemo } from 'react';

import type {
  DesktopImplementedRouteModule,
  DesktopRouteModuleLoader,
  DesktopRouteSurfaceProps,
} from '../navigation/desktopRouteModule';
import type { InvitationAcceptancePageProps } from './InvitationAcceptancePage';

export type InvitationAcceptanceRouteBinding = InvitationAcceptancePageProps;

export function createInvitationAcceptanceRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding(): InvitationAcceptanceRouteBinding;
}>): DesktopRouteModuleLoader {
  if (typeof createBinding !== 'function') {
    throw new Error('invitation_acceptance_route_binding_factory_invalid');
  }
  return async () => {
    const { InvitationAcceptancePage } = await import('./InvitationAcceptancePage');

    function InvitationAcceptanceRouteSurface(_: DesktopRouteSurfaceProps) {
      const binding = useMemo(() => createBinding(), [createBinding]);
      return <InvitationAcceptancePage {...binding} />;
    }

    const module: DesktopImplementedRouteModule = Object.freeze({
      routeId: 'invitation-acceptance',
      capability: 'invitation-acceptance',
      localPolicy: 'cloud_only',
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      Surface: InvitationAcceptanceRouteSurface,
    });
    return module;
  };
}
