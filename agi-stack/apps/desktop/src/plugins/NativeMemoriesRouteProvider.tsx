import { useMemo, type ReactNode } from 'react';

import type { AuthState, DesktopRuntimeConfig } from '../types';
import { isIdentityAuthenticated } from '../features/auth/authContextModel';
import type { DesktopCapabilitySnapshot } from '../features/runtime/capabilitySnapshot';
import { PROJECT_MEMORIES_ROUTE_ID } from '../features/project-knowledge/projectMemoriesClient';
import type { NativeMemoriesAuthority } from '../features/project-knowledge/nativeMemoriesController';
import { NativeMemoriesRouteContextProvider } from '../features/project-knowledge/NativeMemoriesRouteContext';
import {
  createDesktopNativeKnowledgeClientV2,
  createDesktopProjectMemoriesClientV2,
  createDesktopProjectMemoriesOperationsV2,
} from './desktopProjectMemoriesAuthorityModuleV2';
import { useOptionalDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';
import '../features/project-knowledge/NativeMemoriesPage.css';

/** Credentials stay inside the existing clients; this context carries no transport config. */
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
  const authority = useMemo<NativeMemoriesAuthority>(() => {
    const available =
      config.mode === 'local' &&
      Boolean(userId && sessionId) &&
      Boolean(generation?.meta.digest) &&
      (generation?.meta.status === 'ready' || generation?.meta.status === 'degraded') &&
      auth.context?.tenant_id === config.tenantId &&
      auth.context?.project_id === config.projectId &&
      capability?.scope.tenant_id === config.tenantId &&
      capability?.scope.project_id === config.projectId &&
      capability?.authority_revision === auth.context?.revision &&
      capability?.provenance === 'observed' &&
      (capability?.availability === 'available' || capability?.availability === 'degraded');
    return Object.freeze({
      scope: Object.freeze({
        authority: config.mode,
        tenantId: config.tenantId,
        projectId: config.projectId,
      }),
      userId,
      sessionId,
      contextRevision: auth.context?.revision ?? null,
      generationDigest: generation?.meta.digest ?? null,
      available,
      allowedActions: Object.freeze(available ? (JSON.parse(actions) as string[]) : []),
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
    capability?.availability,
    actions,
    generation?.meta.digest,
    generation?.meta.status,
  ]);
  const binding = useMemo(() => {
    const operations = createDesktopProjectMemoriesOperationsV2(() => generation?.actions ?? null);
    return Object.freeze({
      authority,
      client: createDesktopNativeKnowledgeClientV2(operations, config),
      listClient: createDesktopProjectMemoriesClientV2(operations, config),
    });
  }, [authority, config, generation?.actions]);
  return (
    <NativeMemoriesRouteContextProvider value={binding}>
      {children}
    </NativeMemoriesRouteContextProvider>
  );
}
