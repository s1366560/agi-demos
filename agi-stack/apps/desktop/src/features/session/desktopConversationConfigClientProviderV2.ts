import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopConversationConfigMethod = 'updateAgentConversationConfig';

export type DesktopConversationConfigClient = Readonly<
  Pick<DesktopApiClient, DesktopConversationConfigMethod>
>;

export type DesktopConversationConfigClientProviderReasonCodeV2 =
  'desktop_conversation_config_client_unpublished';

export class DesktopConversationConfigClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopConversationConfigClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopConversationConfigClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopConversationConfigClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopConversationConfigClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopConversationConfigClientBindingV2 = Readonly<{
  client: DesktopConversationConfigClient;
  bindOperation: (config: DesktopRuntimeConfig) => DesktopConversationConfigClient;
}>;

export type DesktopConversationConfigClientProviderV2 = Readonly<{
  publish: (
    input: DesktopConversationConfigClientProviderInputV2,
  ) => DesktopConversationConfigClientBindingV2;
  resolve: () => DesktopConversationConfigClientBindingV2;
}>;

export function createDesktopConversationConfigClientProviderV2():
  DesktopConversationConfigClientProviderV2 {
  let publication: DesktopConversationConfigClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopConversationConfigClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopConversationConfigClientProviderErrorV2(
          'desktop_conversation_config_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopConversationConfigClientBindingV2(
  input: DesktopConversationConfigClientProviderInputV2,
): DesktopConversationConfigClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopConversationConfigClient(config),
    bindOperation: (operationConfig) =>
      createDesktopConversationConfigClient(Object.freeze({ ...operationConfig })),
  });
}

function createDesktopConversationConfigClient(
  config: DesktopRuntimeConfig,
): DesktopConversationConfigClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    updateAgentConversationConfig: (
      ...args: Parameters<DesktopApiClient['updateAgentConversationConfig']>
    ) => authority.updateAgentConversationConfig(...args),
  });
}
