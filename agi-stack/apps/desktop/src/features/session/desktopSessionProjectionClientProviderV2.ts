import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopSessionProjectionMethod = 'getConversationSession';

export type DesktopSessionProjectionClient = Readonly<
  Pick<DesktopApiClient, DesktopSessionProjectionMethod>
>;

export type DesktopSessionProjectionClientProviderReasonCodeV2 =
  'desktop_session_projection_client_unpublished';

export class DesktopSessionProjectionClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopSessionProjectionClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopSessionProjectionClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopSessionProjectionClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopSessionProjectionClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopSessionProjectionClientBindingV2 = Readonly<{
  client: DesktopSessionProjectionClient;
  bindOperation: (config: DesktopRuntimeConfig) => DesktopSessionProjectionClient;
}>;

export type DesktopSessionProjectionClientProviderV2 = Readonly<{
  publish: (
    input: DesktopSessionProjectionClientProviderInputV2,
  ) => DesktopSessionProjectionClientBindingV2;
  resolve: () => DesktopSessionProjectionClientBindingV2;
}>;

export function createDesktopSessionProjectionClientProviderV2():
  DesktopSessionProjectionClientProviderV2 {
  let publication: DesktopSessionProjectionClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopSessionProjectionClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopSessionProjectionClientProviderErrorV2(
          'desktop_session_projection_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopSessionProjectionClientBindingV2(
  input: DesktopSessionProjectionClientProviderInputV2,
): DesktopSessionProjectionClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopSessionProjectionClient(config),
    bindOperation: (operationConfig) =>
      createDesktopSessionProjectionClient(Object.freeze({ ...operationConfig })),
  });
}

function createDesktopSessionProjectionClient(
  config: DesktopRuntimeConfig,
): DesktopSessionProjectionClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    getConversationSession: (
      ...args: Parameters<DesktopApiClient['getConversationSession']>
    ) => authority.getConversationSession(...args),
  });
}
