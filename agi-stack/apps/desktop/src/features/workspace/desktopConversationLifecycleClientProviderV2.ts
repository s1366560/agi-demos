import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopConversationLifecycleMethod =
  | 'deleteAgentConversation'
  | 'generateAgentConversationSummary'
  | 'updateAgentConversationTitle';

export type DesktopConversationLifecycleClient = Readonly<
  Pick<DesktopApiClient, DesktopConversationLifecycleMethod>
>;

export type DesktopConversationLifecycleClientProviderReasonCodeV2 =
  'desktop_conversation_lifecycle_client_unpublished';

export class DesktopConversationLifecycleClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopConversationLifecycleClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopConversationLifecycleClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopConversationLifecycleClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopConversationLifecycleClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopConversationLifecycleClientBindingV2 = Readonly<{
  client: DesktopConversationLifecycleClient;
}>;

export type DesktopConversationLifecycleClientProviderV2 = Readonly<{
  publish: (
    input: DesktopConversationLifecycleClientProviderInputV2,
  ) => DesktopConversationLifecycleClientBindingV2;
  resolve: () => DesktopConversationLifecycleClientBindingV2;
}>;

export function createDesktopConversationLifecycleClientProviderV2():
  DesktopConversationLifecycleClientProviderV2 {
  let publication: DesktopConversationLifecycleClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopConversationLifecycleClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopConversationLifecycleClientProviderErrorV2(
          'desktop_conversation_lifecycle_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopConversationLifecycleClientBindingV2(
  input: DesktopConversationLifecycleClientProviderInputV2,
): DesktopConversationLifecycleClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  const authority = new DesktopApiClient(config);
  const client: DesktopConversationLifecycleClient = Object.freeze({
    deleteAgentConversation: (
      ...args: Parameters<DesktopApiClient['deleteAgentConversation']>
    ) => authority.deleteAgentConversation(...args),
    generateAgentConversationSummary: (
      ...args: Parameters<DesktopApiClient['generateAgentConversationSummary']>
    ) => authority.generateAgentConversationSummary(...args),
    updateAgentConversationTitle: (
      ...args: Parameters<DesktopApiClient['updateAgentConversationTitle']>
    ) => authority.updateAgentConversationTitle(...args),
  });
  return Object.freeze({ client });
}
