import {
  CLOUD_SOCKET_CLOSED,
  CLOUD_SOCKET_CLOSING,
  CLOUD_SOCKET_OPEN,
} from '../../api/cloudSocketBridge';
import type { ProjectKnowledgeScope } from '../project-knowledge/projectKnowledgeClient';

export type ProjectPlaybooksEventSocket = {
  readyState: number;
  onopen: (() => void) | null;
  onmessage: ((event: Readonly<{ data: string | ArrayBuffer }>) => void) | null;
  onerror: (() => void) | null;
  onclose: (() => void) | null;
  send(payload: string): void;
  close(code?: number, reason?: string): void;
};

export type ProjectPlaybooksEventSource = Readonly<{
  subscribe(scope: ProjectKnowledgeScope, listener: () => void): () => void;
}>;

export type ProjectPlaybooksEventSourceDependencies = Readonly<{
  openSocket(scope: ProjectKnowledgeScope): ProjectPlaybooksEventSocket;
}>;

export function createProjectPlaybooksEventSource(
  dependencies: ProjectPlaybooksEventSourceDependencies,
): ProjectPlaybooksEventSource {
  if (typeof dependencies.openSocket !== 'function') {
    throw new Error('project_playbooks_event_socket_factory_invalid');
  }
  return Object.freeze({
    subscribe(scopeInput, listener) {
      const scope = requireCloudProjectScope(scopeInput);
      if (typeof listener !== 'function') {
        throw new Error('project_playbooks_event_listener_invalid');
      }
      const socket = dependencies.openSocket(scope);
      let active = true;
      socket.onopen = () => {
        if (!active || socket.readyState !== CLOUD_SOCKET_OPEN) return;
        sendProjectSubscription(socket, 'subscribe_project_events', scope.projectId);
      };
      socket.onmessage = (event) => {
        if (!active || typeof event.data !== 'string') return;
        if (reflectionCompleteProjectId(event.data) === scope.projectId) listener();
      };
      return () => {
        if (!active) return;
        active = false;
        if (socket.readyState === CLOUD_SOCKET_OPEN) {
          sendProjectSubscription(socket, 'unsubscribe_project_events', scope.projectId);
        }
        socket.onopen = null;
        socket.onmessage = null;
        socket.onerror = null;
        socket.onclose = null;
        if (
          socket.readyState !== CLOUD_SOCKET_CLOSING &&
          socket.readyState !== CLOUD_SOCKET_CLOSED
        ) {
          socket.close(1000, 'project_playbooks_unsubscribe');
        }
      };
    },
  });
}

function sendProjectSubscription(
  socket: ProjectPlaybooksEventSocket,
  type: 'subscribe_project_events' | 'unsubscribe_project_events',
  projectId: string,
): void {
  socket.send(JSON.stringify({ type, project_id: projectId }));
}

function reflectionCompleteProjectId(payload: string): string | null {
  let value: unknown;
  try {
    value = JSON.parse(payload) as unknown;
  } catch {
    return null;
  }
  if (!isRecord(value) || value.type !== 'reflection_complete') return null;
  return nonEmpty(value.project_id);
}

function requireCloudProjectScope(scope: ProjectKnowledgeScope): ProjectKnowledgeScope {
  const tenantId = nonEmpty(scope.tenantId);
  const projectId = nonEmpty(scope.projectId);
  if (scope.authority !== 'cloud' || !tenantId || !projectId) {
    throw new Error('project_playbooks_event_scope_invalid');
  }
  return Object.freeze({ authority: 'cloud', tenantId, projectId });
}

function nonEmpty(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 && value === value.trim() ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
