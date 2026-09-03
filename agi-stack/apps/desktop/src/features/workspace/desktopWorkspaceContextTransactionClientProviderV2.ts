import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopWorkspaceContextTransactionMethod =
  | 'listProjects'
  | 'getWorkspaceContext'
  | 'switchWorkspaceContext';

export type DesktopWorkspaceContextTransactionClient = Readonly<
  Pick<DesktopApiClient, DesktopWorkspaceContextTransactionMethod>
>;

export type DesktopWorkspaceContextTransactionClientProviderReasonCodeV2 =
  | 'desktop_workspace_context_transaction_client_unpublished'
  | 'desktop_workspace_context_transaction_generation_unavailable';

export class DesktopWorkspaceContextTransactionClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopWorkspaceContextTransactionClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopWorkspaceContextTransactionClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopWorkspaceContextTransactionClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopWorkspaceContextTransactionClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopWorkspaceContextTransactionClientBindingV2 = Readonly<{
  client: DesktopWorkspaceContextTransactionClient;
  bindOperation: (
    config: DesktopRuntimeConfig,
  ) => DesktopWorkspaceContextTransactionClient;
}>;

export type DesktopWorkspaceContextTransactionClientProviderV2 = Readonly<{
  publish: (
    input: DesktopWorkspaceContextTransactionClientProviderInputV2,
  ) => DesktopWorkspaceContextTransactionClientBindingV2;
  resolve: () => DesktopWorkspaceContextTransactionClientBindingV2;
}>;

export type DesktopWorkspaceContextOperationLeaseV2 = Readonly<{
  digest: string | undefined;
  kind: 'authentication-kernel' | 'generation';
  release: () => Promise<void>;
}>;

export type DesktopWorkspaceContextOperationLeaseFactoryV2 =
  () => DesktopWorkspaceContextOperationLeaseV2;

export function createDesktopWorkspaceContextTransactionClientProviderV2():
  DesktopWorkspaceContextTransactionClientProviderV2 {
  let publication: DesktopWorkspaceContextTransactionClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopWorkspaceContextTransactionClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopWorkspaceContextTransactionClientProviderErrorV2(
          'desktop_workspace_context_transaction_client_unpublished',
        );
      }
      return publication;
    },
  });
}

export async function runDesktopWorkspaceContextOperationV2<T>(
  acquireOperationLease: DesktopWorkspaceContextOperationLeaseFactoryV2,
  operation: () => Promise<T>,
): Promise<T> {
  const lease = acquireOperationLease();
  let operationFailed = false;
  try {
    if (lease.kind !== 'generation' || !lease.digest?.trim()) {
      throw new DesktopWorkspaceContextTransactionClientProviderErrorV2(
        'desktop_workspace_context_transaction_generation_unavailable',
      );
    }
    return await operation();
  } catch (error) {
    operationFailed = true;
    throw error;
  } finally {
    try {
      await lease.release();
    } catch (error) {
      if (!operationFailed) throw error;
    }
  }
}

function createDesktopWorkspaceContextTransactionClientBindingV2(
  input: DesktopWorkspaceContextTransactionClientProviderInputV2,
): DesktopWorkspaceContextTransactionClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopWorkspaceContextTransactionClient(config),
    bindOperation: (operationConfig) =>
      createDesktopWorkspaceContextTransactionClient(
        Object.freeze({ ...operationConfig }),
      ),
  });
}

function createDesktopWorkspaceContextTransactionClient(
  config: DesktopRuntimeConfig,
): DesktopWorkspaceContextTransactionClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    listProjects: (...args: Parameters<DesktopApiClient['listProjects']>) =>
      authority.listProjects(...args),
    getWorkspaceContext: (
      ...args: Parameters<DesktopApiClient['getWorkspaceContext']>
    ) => authority.getWorkspaceContext(...args),
    switchWorkspaceContext: (
      ...args: Parameters<DesktopApiClient['switchWorkspaceContext']>
    ) => authority.switchWorkspaceContext(...args),
  });
}
