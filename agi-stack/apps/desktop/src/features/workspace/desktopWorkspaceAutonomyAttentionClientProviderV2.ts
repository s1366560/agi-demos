import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopWorkspaceAutonomyAttentionMethod =
  | 'listWorkspaceAutonomyAttentions'
  | 'getWorkspaceAuthorityRevision'
  | 'retryWorkspaceAutonomyAttention'
  | 'resolveWorkspaceAutonomyAttention';

export type DesktopWorkspaceAutonomyAttentionClient = Readonly<
  Pick<DesktopApiClient, DesktopWorkspaceAutonomyAttentionMethod>
>;

export type DesktopWorkspaceAutonomyAttentionClientProviderReasonCodeV2 =
  'desktop_workspace_autonomy_attention_client_unpublished';

export class DesktopWorkspaceAutonomyAttentionClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopWorkspaceAutonomyAttentionClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopWorkspaceAutonomyAttentionClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopWorkspaceAutonomyAttentionClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopWorkspaceAutonomyAttentionClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopWorkspaceAutonomyAttentionClientBindingV2 = Readonly<{
  client: DesktopWorkspaceAutonomyAttentionClient;
  bindOperation: (
    config: DesktopRuntimeConfig,
  ) => DesktopWorkspaceAutonomyAttentionClient;
}>;

export type DesktopWorkspaceAutonomyAttentionClientProviderV2 = Readonly<{
  publish: (
    input: DesktopWorkspaceAutonomyAttentionClientProviderInputV2,
  ) => DesktopWorkspaceAutonomyAttentionClientBindingV2;
  resolve: () => DesktopWorkspaceAutonomyAttentionClientBindingV2;
}>;

export function createDesktopWorkspaceAutonomyAttentionClientProviderV2():
  DesktopWorkspaceAutonomyAttentionClientProviderV2 {
  let publication: DesktopWorkspaceAutonomyAttentionClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopWorkspaceAutonomyAttentionClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopWorkspaceAutonomyAttentionClientProviderErrorV2(
          'desktop_workspace_autonomy_attention_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopWorkspaceAutonomyAttentionClientBindingV2(
  input: DesktopWorkspaceAutonomyAttentionClientProviderInputV2,
): DesktopWorkspaceAutonomyAttentionClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopWorkspaceAutonomyAttentionClient(config),
    bindOperation: (operationConfig) =>
      createDesktopWorkspaceAutonomyAttentionClient(
        Object.freeze({ ...operationConfig }),
      ),
  });
}

function createDesktopWorkspaceAutonomyAttentionClient(
  config: DesktopRuntimeConfig,
): DesktopWorkspaceAutonomyAttentionClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    listWorkspaceAutonomyAttentions: (
      ...args: Parameters<DesktopApiClient['listWorkspaceAutonomyAttentions']>
    ) => authority.listWorkspaceAutonomyAttentions(...args),
    getWorkspaceAuthorityRevision: (
      ...args: Parameters<DesktopApiClient['getWorkspaceAuthorityRevision']>
    ) => authority.getWorkspaceAuthorityRevision(...args),
    retryWorkspaceAutonomyAttention: (
      ...args: Parameters<DesktopApiClient['retryWorkspaceAutonomyAttention']>
    ) => authority.retryWorkspaceAutonomyAttention(...args),
    resolveWorkspaceAutonomyAttention: (
      ...args: Parameters<DesktopApiClient['resolveWorkspaceAutonomyAttention']>
    ) => authority.resolveWorkspaceAutonomyAttention(...args),
  });
}
