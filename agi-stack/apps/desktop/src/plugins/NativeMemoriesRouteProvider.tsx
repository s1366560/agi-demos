import { desktopNativeCloudAuthClient } from '../api/nativeCloudAuthClient';
import { createDesktopNativeKnowledgeInputsClientV2 } from './desktopNativeKnowledgeInputsClientV2';
import {
  createDesktopTenantProvidersOperationsV2,
  createDesktopTenantProvidersClientV2,
} from './desktopTenantProvidersAuthorityModuleV2';
import { createDesktopWorkspaceCatalogOperationsV2 } from './desktopWorkspaceCatalogAuthorityModuleV2';
import { useMemo, useRef, type ReactNode } from 'react';

import type { AuthState, DesktopRuntimeConfig } from '../types';
import { isIdentityAuthenticated } from '../features/auth/authContextModel';
import type { DesktopCapabilitySnapshot } from '../features/runtime/capabilitySnapshot';
import { PROJECT_MEMORIES_ROUTE_ID } from '../features/project-knowledge/projectMemoriesClient';
import type { NativeMemoriesAuthority } from '../features/project-knowledge/nativeMemoriesController';
import type { CloudMemoryUiAuthority } from '../features/project-knowledge/cloudMemoryUiAuthority';
import { NativeMemoriesRouteContextProvider } from '../features/project-knowledge/NativeMemoriesRouteContext';
import { CloudMemoryRouteContextProvider } from '../features/project-knowledge/CloudMemoryRouteContext';
import {
  createDesktopNativeKnowledgeClientV2,
  createDesktopNativeKnowledgeConnectionClientV2,
  createDesktopProjectMemoriesClientV2,
  createDesktopProjectMemoriesOperationsV2,
  createDesktopCloudMemoryClientV2,
  createDesktopNativeKnowledgeProcessingClientV2,
  createDesktopNativeKnowledgeProcessingCommandClientV2,
} from './desktopProjectMemoriesAuthorityModuleV2';
import { useOptionalDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';
import '../features/project-knowledge/NativeMemoriesPage.css';

/** Credentials stay inside the existing clients; route contexts carry no transport config. */
export function NativeMemoriesRouteProvider({
  config,
  auth,
  capabilitySnapshot,
  children,
}: Readonly<{
  config: DesktopRuntimeConfig;
  auth: AuthState;
  capabilitySnapshot: DesktopCapabilitySnapshot | null;
  children: ReactNode;
}>) {
  const generation = useOptionalDesktopRendererGenerationV2();
  const capability = capabilitySnapshot?.capabilities[PROJECT_MEMORIES_ROUTE_ID];
  const authenticated = isIdentityAuthenticated(auth);
  const userId = authenticated ? (auth.user?.user_id ?? null) : null;
  const sessionId = authenticated ? (auth.session?.session_id ?? null) : null;
  const actions = JSON.stringify(capability?.allowed_actions ?? []);
  const authorities = useMemo<
    Readonly<{ native: NativeMemoriesAuthority; cloud: CloudMemoryUiAuthority }>
  >(() => {
    const available =
      Boolean(userId && sessionId) &&
      Boolean(generation?.meta.digest) &&
      (generation?.meta.status === 'ready' || generation?.meta.status === 'degraded') &&
      auth.context?.tenant_id === config.tenantId &&
      auth.context?.project_id === config.projectId &&
      capability?.scope.tenant_id === config.tenantId &&
      capability?.scope.project_id === config.projectId &&
      capability?.authority_revision === auth.context?.revision &&
      capability?.provenance === 'observed' &&
      capability?.authority_source === (config.mode === 'local' ? 'sidecar' : 'cloud_service') &&
      (capability?.availability === 'available' || capability?.availability === 'degraded');
    const shared = Object.freeze({
      scope: Object.freeze({
        authority: config.mode,
        tenantId: config.tenantId,
        projectId: config.projectId,
      }),
      sessionId,
      contextRevision: auth.context?.revision ?? null,
      generationDigest: generation?.meta.digest ?? null,
    });
    const allowed = Object.freeze(available ? (JSON.parse(actions) as string[]) : []);
    return Object.freeze({
      native: Object.freeze({
        ...shared,
        userId,
        available: available && config.mode === 'local',
        allowedActions: config.mode === 'local' ? allowed : Object.freeze([]),
      }),
      cloud: Object.freeze({
        ...shared,
        actorId: userId,
        available: available && config.mode === 'cloud',
        allowedActions: config.mode === 'cloud' ? allowed : Object.freeze([]),
      }),
    });
  }, [
    config.mode,
    config.tenantId,
    config.projectId,
    userId,
    sessionId,
    auth.context?.tenant_id,
    auth.context?.project_id,
    auth.context?.revision,
    capability?.scope.tenant_id,
    capability?.scope.project_id,
    capability?.authority_revision,
    capability?.provenance,
    capability?.authority_source,
    capability?.availability,
    actions,
    generation?.meta.digest,
    generation?.meta.status,
  ]);
  // Retained transports consult live capabilities and lose access as soon as identity changes.
  const live = useRef({ authorities, capability });
  live.current = { authorities, capability };
  const bindings = useMemo(() => {
    const operations = createDesktopProjectMemoriesOperationsV2(
      () => generation?.actions ?? null,
      () =>
        live.current.authorities === authorities && authorities.native.available
          ? (live.current.capability ?? null)
          : null,
    );
    const listClient = createDesktopProjectMemoriesClientV2(operations, config);
    const processingClient = createDesktopNativeKnowledgeProcessingClientV2(operations, config);
    const processingInputsClient = authorities.native.available
      ? createDesktopNativeKnowledgeInputsClientV2(config, {
          processing: processingClient,
          providers: createDesktopTenantProvidersClientV2(
            createDesktopTenantProvidersOperationsV2(() => generation?.actions ?? null),
            config,
          ),
          workspaces: createDesktopWorkspaceCatalogOperationsV2(() => generation?.actions ?? null),
          isCurrent: (operation) =>
            live.current.authorities === authorities &&
            authorities.native.available &&
            authorities.native.allowedActions.includes(operation),
        })
      : undefined;
    return Object.freeze({
      native: Object.freeze({
        authority: authorities.native,
        connectionClient: createDesktopNativeKnowledgeConnectionClientV2(operations, config),
        cloudAuthClient: desktopNativeCloudAuthClient(),
        client: createDesktopNativeKnowledgeClientV2(operations, config),
        listClient,
        processingClient,
        processingInputsClient,
        processingCommandClient: createDesktopNativeKnowledgeProcessingCommandClientV2(
          operations,
          config,
        ),
      }),
      cloud: Object.freeze({
        authority: authorities.cloud,
        listClient,
        client: createDesktopCloudMemoryClientV2(operations, config),
      }),
    });
  }, [authorities, config, generation?.actions]);
  return (
    <NativeMemoriesRouteContextProvider value={bindings.native}>
      <CloudMemoryRouteContextProvider value={bindings.cloud}>
        {children}
      </CloudMemoryRouteContextProvider>
    </NativeMemoriesRouteContextProvider>
  );
}
