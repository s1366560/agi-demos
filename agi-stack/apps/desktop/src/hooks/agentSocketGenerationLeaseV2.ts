import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererOperationLeaseV2,
} from '../plugins/desktopRendererGenerationContextV2';

export type AgentSocketGenerationLeaseFactoryV2 =
  DesktopRendererGenerationActionsV2['acquireOperationLease'];

export type AgentSocketGenerationLeaseAdmissionV2 =
  | Readonly<{
      constructSocket: <TSocket>(constructor: () => TSocket) => TSocket;
      digest: string;
      release: () => Promise<void>;
      status: 'accepted';
    }>
  | Readonly<{
      reasonCode:
        | 'desktop_agent_socket_generation_digest_missing'
        | 'desktop_agent_socket_generation_lease_acquire_failed'
        | 'desktop_agent_socket_generation_lease_invalid'
        | 'desktop_agent_socket_generation_required';
      status: 'rejected';
    }>;

function isDesktopRendererOperationLeaseV2(
  value: unknown,
): value is DesktopRendererOperationLeaseV2 {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Partial<DesktopRendererOperationLeaseV2>;
  return (
    (candidate.kind === 'authentication-kernel' || candidate.kind === 'generation') &&
    (candidate.digest === undefined || typeof candidate.digest === 'string') &&
    typeof candidate.release === 'function'
  );
}

function releaseDesktopRendererOperationLeaseV2(
  lease: DesktopRendererOperationLeaseV2,
): Promise<void> {
  try {
    return Promise.resolve(lease.release()).catch(() => undefined);
  } catch {
    return Promise.resolve();
  }
}

export function acquireAgentSocketGenerationLeaseV2(
  acquireGenerationLease: AgentSocketGenerationLeaseFactoryV2,
): AgentSocketGenerationLeaseAdmissionV2 {
  let candidate: unknown;
  try {
    candidate = acquireGenerationLease();
  } catch {
    return Object.freeze({
      reasonCode: 'desktop_agent_socket_generation_lease_acquire_failed',
      status: 'rejected',
    });
  }

  if (!isDesktopRendererOperationLeaseV2(candidate)) {
    return Object.freeze({
      reasonCode: 'desktop_agent_socket_generation_lease_invalid',
      status: 'rejected',
    });
  }

  const lease = candidate;
  if (lease.kind !== 'generation') {
    void releaseDesktopRendererOperationLeaseV2(lease);
    return Object.freeze({
      reasonCode: 'desktop_agent_socket_generation_required',
      status: 'rejected',
    });
  }

  const digest = lease.digest?.trim() ?? '';
  if (!digest) {
    void releaseDesktopRendererOperationLeaseV2(lease);
    return Object.freeze({
      reasonCode: 'desktop_agent_socket_generation_digest_missing',
      status: 'rejected',
    });
  }

  let released = false;
  let releasePromise: Promise<void> | undefined;
  return Object.freeze({
    constructSocket: <TSocket>(constructor: () => TSocket): TSocket => {
      if (released) {
        throw new Error('desktop_agent_socket_generation_lease_released');
      }
      return constructor();
    },
    digest,
    release: () => {
      if (!releasePromise) {
        released = true;
        releasePromise = releaseDesktopRendererOperationLeaseV2(lease);
      }
      return releasePromise;
    },
    status: 'accepted',
  });
}
