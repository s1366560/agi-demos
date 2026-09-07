import type { VaultBoundCloudRequestBroker } from '../../api/cloudRequestBroker';
import type { DesktopWorkspaceRosterOperationsV2 } from '../../plugins/desktopWorkspaceRosterAuthorityModuleV2';
import type { AuthState, DesktopRuntimeConfig } from '../../types';
import { deviceApprovalCapability } from '../device-approval/deviceApprovalCapability';
import { invitationAcceptanceCapability } from '../invitation-acceptance/invitationAcceptanceCapability';
import type { DesktopCapabilitySnapshot } from '../runtime/capabilitySnapshot';
import { tenantCreationCapability } from '../tenant-creation/tenantCreationCapability';
import type { DesktopRouteCapabilityResolver } from './desktopHashRouteHost';
import type { DesktopRouteRuntimeMode } from './desktopRouteHostModel';
import {
  DEVICE_APPROVAL_ROUTE_ID,
  INVITATION_ACCEPTANCE_ROUTE_ID,
  TENANT_CREATION_ROUTE_ID,
} from './desktopProductionRouteRegistry';
import {
  desktopRouteBasePermissionsForAuth,
  resolveDesktopRouteCapability,
} from './desktopProductionRouteRuntime';
import {
  createCloudDesktopRoutePermissionResolver,
  createLocalDesktopRoutePermissionResolver,
  type DesktopRoutePermissionSnapshotResolver,
} from './desktopRoutePermissionAuthority';
import {
  createCloudDesktopRoutePermissionClient,
  createLocalDesktopRoutePermissionClient,
  createVaultBoundCloudDesktopRoutePermissionClient,
} from './desktopRoutePermissionHttpClient';

export type DesktopProductionRouteAuthorityProviderReasonCodeV2 =
  'desktop_production_route_authority_unpublished';

export class DesktopProductionRouteAuthorityProviderErrorV2 extends Error {
  readonly reasonCode: DesktopProductionRouteAuthorityProviderReasonCodeV2;

  constructor(reasonCode: DesktopProductionRouteAuthorityProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopProductionRouteAuthorityProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopProductionRouteAuthorityInputV2 = Readonly<{
  auth: AuthState;
  config: DesktopRuntimeConfig;
  capabilitySnapshot: DesktopCapabilitySnapshot | null;
  cloudRequestBroker: VaultBoundCloudRequestBroker | null;
  workspaceRosterOperationsV2: DesktopWorkspaceRosterOperationsV2;
}>;

export type DesktopProductionRouteAuthorityBindingV2 = Readonly<{
  mode: DesktopRouteRuntimeMode;
  permissions: ReadonlySet<string>;
  resolveCapability: DesktopRouteCapabilityResolver;
  resolvePermissionSnapshot: DesktopRoutePermissionSnapshotResolver;
}>;

export type DesktopProductionRouteAuthorityProviderV2 = Readonly<{
  publish: (
    input: DesktopProductionRouteAuthorityInputV2
  ) => DesktopProductionRouteAuthorityBindingV2;
  resolve: () => DesktopProductionRouteAuthorityBindingV2;
}>;

export function createDesktopProductionRouteAuthorityProviderV2(): DesktopProductionRouteAuthorityProviderV2 {
  let publication: DesktopProductionRouteAuthorityBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopProductionRouteAuthorityBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopProductionRouteAuthorityProviderErrorV2(
          'desktop_production_route_authority_unpublished'
        );
      }
      return publication;
    },
  });
}

function createDesktopProductionRouteAuthorityBindingV2(
  input: DesktopProductionRouteAuthorityInputV2
): DesktopProductionRouteAuthorityBindingV2 {
  const config = Object.freeze({ ...input.config });
  const observedRuntimeMode = input.capabilitySnapshot?.runtime_state;
  const mode =
    observedRuntimeMode && observedRuntimeMode !== 'native' ? observedRuntimeMode : config.mode;
  const permissions = Object.freeze(desktopRouteBasePermissionsForAuth(input.auth));
  const resolvePermissionSnapshot = createPermissionSnapshotResolver({
    cloudRequestBroker: input.cloudRequestBroker,
    config,
    mode,
    workspaceRosterOperationsV2: input.workspaceRosterOperationsV2,
  });
  const resolveCapability: DesktopRouteCapabilityResolver = (capability, context) => {
    if (capability === DEVICE_APPROVAL_ROUTE_ID) {
      return deviceApprovalCapability(config);
    }
    if (capability === TENANT_CREATION_ROUTE_ID) {
      return tenantCreationCapability(config);
    }
    if (capability === INVITATION_ACCEPTANCE_ROUTE_ID) {
      return invitationAcceptanceCapability(config);
    }
    return resolveDesktopRouteCapability(input.capabilitySnapshot, capability, context);
  };

  return Object.freeze({
    mode,
    permissions,
    resolveCapability,
    resolvePermissionSnapshot,
  });
}

function createPermissionSnapshotResolver(
  input: Readonly<{
    cloudRequestBroker: VaultBoundCloudRequestBroker | null;
    config: DesktopRuntimeConfig;
    mode: DesktopRouteRuntimeMode;
    workspaceRosterOperationsV2: DesktopWorkspaceRosterOperationsV2;
  }>
): DesktopRoutePermissionSnapshotResolver {
  if (input.config.mode === 'cloud') {
    return createCloudDesktopRoutePermissionResolver({
      client: createCloudDesktopRoutePermissionClient(
        input.config,
        input.workspaceRosterOperationsV2,
        input.cloudRequestBroker,
      ),
    });
  }

  const localResolver = createLocalDesktopRoutePermissionResolver({
    client: createLocalDesktopRoutePermissionClient(
      input.config,
      input.workspaceRosterOperationsV2,
    ),
  });
  const localOnlineCloudResolver = input.cloudRequestBroker
    ? createCloudDesktopRoutePermissionResolver({
        client: createVaultBoundCloudDesktopRoutePermissionClient(
          input.config,
          input.cloudRequestBroker,
          input.workspaceRosterOperationsV2,
        ),
      })
    : null;
  return (context, signal, match) => {
    if (input.mode === 'local_online' && match.definition.localPolicy === 'cloud_only') {
      if (localOnlineCloudResolver === null) {
        return Promise.reject(new Error('cloud_request_broker_missing'));
      }
      return localOnlineCloudResolver(context, signal, match);
    }
    return localResolver(context, signal, match);
  };
}
