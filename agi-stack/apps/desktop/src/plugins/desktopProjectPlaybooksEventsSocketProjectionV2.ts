import { DesktopApiClient } from '../api/client';
import {
  desktopCloudSessionProjectionClient,
  type CloudSessionProjectionClient,
} from '../api/cloudSessionProjectionClient';
import {
  createCloudSocketBridge,
  desktopCloudSocketTransport,
  type CloudSocketBridgeTransport,
} from '../api/cloudSocketBridge';
import {
  createProjectPlaybooksEventSource,
  type ProjectPlaybooksEventSocket,
} from '../features/project-playbooks/projectPlaybooksEventSource';
import type { ProjectKnowledgeScope } from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopRuntimeConfig } from '../types';
import {
  cloneDesktopProjectPlaybooksEventsConfigV2,
  cloneDesktopProjectPlaybooksEventsScopeV2,
} from './desktopProjectPlaybooksEventsOperationContractV2';

export type DesktopProjectPlaybooksEventsSocketDependenciesV2 = Readonly<{
  projectionClient: CloudSessionProjectionClient | null;
  transport(): CloudSocketBridgeTransport | null;
  sessionId(): string;
}>;

export type DesktopProjectPlaybooksEventsSocketAuthorityV2 = Readonly<{
  subscribe(listener: () => void): () => void;
}>;

export function createDesktopProjectPlaybooksEventsSocketAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: ProjectKnowledgeScope,
  dependencies: DesktopProjectPlaybooksEventsSocketDependenciesV2 =
    productionDependenciesV2(),
): DesktopProjectPlaybooksEventsSocketAuthorityV2 {
  const runtimeConfig = cloneDesktopProjectPlaybooksEventsConfigV2(config);
  const operationScope = cloneDesktopProjectPlaybooksEventsScopeV2(scope, runtimeConfig);
  if (runtimeConfig.mode === 'local') {
    return Object.freeze({ subscribe: () => () => undefined });
  }
  if (operationScope.authority !== 'cloud') {
    throw new Error('desktop_project_playbooks_events_authority_mismatch');
  }
  return Object.freeze({
    subscribe(listener) {
      if (typeof listener !== 'function') {
        throw new Error('project_playbooks_event_listener_invalid');
      }
      const controller = new AbortController();
      let active = true;
      let disconnect: (() => void) | null = null;
      const connect = async (): Promise<void> => {
        const projection = await dependencies.projectionClient?.load(controller.signal);
        if (!active) return;
        if (!projection) throw new Error('cloud_session_projection_unavailable');
        const transport = dependencies.transport();
        if (!transport) throw new Error('cloud_socket_broker_missing');
        const cloudConfig = Object.freeze({
          ...runtimeConfig,
          apiBaseUrl: projection.apiBaseUrl,
          deviceAuthorizationBaseUrl: projection.apiBaseUrl,
        });
        const source = createProjectPlaybooksEventSource({
          openSocket(currentScope) {
            const sessionId = canonicalStringV2(dependencies.sessionId());
            if (sessionId === null) {
              throw new Error('project_playbooks_event_session_invalid');
            }
            const socket = createCloudSocketBridge(
              {
                kind: 'agent',
                url: new DesktopApiClient(cloudConfig).agentWsUrl(sessionId),
                scope: {
                  tenant_id: currentScope.tenantId,
                  project_id: currentScope.projectId,
                  workspace_id: null,
                  conversation_id: null,
                },
              },
              transport,
            );
            return socket as unknown as ProjectPlaybooksEventSocket;
          },
        });
        const nextDisconnect = source.subscribe(operationScope, listener);
        if (active) disconnect = nextDisconnect;
        else nextDisconnect();
      };
      void connect().catch(() => undefined);
      return () => {
        if (!active) return;
        active = false;
        controller.abort();
        disconnect?.();
        disconnect = null;
      };
    },
  });
}

function productionDependenciesV2(): DesktopProjectPlaybooksEventsSocketDependenciesV2 {
  return Object.freeze({
    projectionClient: desktopCloudSessionProjectionClient(),
    transport: desktopCloudSocketTransport,
    sessionId: () => `playbooks_${globalThis.crypto.randomUUID()}`,
  });
}

function canonicalStringV2(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 && value === value.trim()
    ? value
    : null;
}
