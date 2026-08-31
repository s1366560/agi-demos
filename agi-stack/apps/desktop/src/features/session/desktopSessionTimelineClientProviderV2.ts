import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopSessionTimelineMethod = 'getConversationMessages';

export type DesktopSessionTimelineClient = Readonly<
  Pick<DesktopApiClient, DesktopSessionTimelineMethod>
>;

export type DesktopSessionTimelineClientProviderReasonCodeV2 =
  'desktop_session_timeline_client_unpublished';

export class DesktopSessionTimelineClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopSessionTimelineClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopSessionTimelineClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopSessionTimelineClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopSessionTimelineClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopSessionTimelineClientBindingV2 = Readonly<{
  client: DesktopSessionTimelineClient;
  bindOperation: (config: DesktopRuntimeConfig) => DesktopSessionTimelineClient;
}>;

export type DesktopSessionTimelineClientProviderV2 = Readonly<{
  publish: (
    input: DesktopSessionTimelineClientProviderInputV2,
  ) => DesktopSessionTimelineClientBindingV2;
  resolve: () => DesktopSessionTimelineClientBindingV2;
}>;

export function createDesktopSessionTimelineClientProviderV2():
  DesktopSessionTimelineClientProviderV2 {
  let publication: DesktopSessionTimelineClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopSessionTimelineClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopSessionTimelineClientProviderErrorV2(
          'desktop_session_timeline_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopSessionTimelineClientBindingV2(
  input: DesktopSessionTimelineClientProviderInputV2,
): DesktopSessionTimelineClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopSessionTimelineClient(config),
    bindOperation: (operationConfig) =>
      createDesktopSessionTimelineClient(Object.freeze({ ...operationConfig })),
  });
}

function createDesktopSessionTimelineClient(
  config: DesktopRuntimeConfig,
): DesktopSessionTimelineClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    getConversationMessages: (
      ...args: Parameters<DesktopApiClient['getConversationMessages']>
    ) => authority.getConversationMessages(...args),
  });
}
