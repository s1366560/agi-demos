import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopNewThreadCreationMethod =
  | 'createAgentConversation'
  | 'createTaskSession'
  | 'runAgentMessage';

export type DesktopNewThreadCreationClient = Readonly<
  Pick<DesktopApiClient, DesktopNewThreadCreationMethod>
>;

export type DesktopNewThreadCreationClientProviderReasonCodeV2 =
  'desktop_new_thread_creation_client_unpublished';

export class DesktopNewThreadCreationClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopNewThreadCreationClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopNewThreadCreationClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopNewThreadCreationClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopNewThreadCreationClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopNewThreadCreationClientBindingV2 = Readonly<{
  client: DesktopNewThreadCreationClient;
  bindOperation: (config: DesktopRuntimeConfig) => DesktopNewThreadCreationClient;
}>;

export type DesktopNewThreadCreationClientProviderV2 = Readonly<{
  publish: (
    input: DesktopNewThreadCreationClientProviderInputV2,
  ) => DesktopNewThreadCreationClientBindingV2;
  resolve: () => DesktopNewThreadCreationClientBindingV2;
}>;

export function createDesktopNewThreadCreationClientProviderV2():
  DesktopNewThreadCreationClientProviderV2 {
  let publication: DesktopNewThreadCreationClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopNewThreadCreationClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopNewThreadCreationClientProviderErrorV2(
          'desktop_new_thread_creation_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopNewThreadCreationClientBindingV2(
  input: DesktopNewThreadCreationClientProviderInputV2,
): DesktopNewThreadCreationClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopNewThreadCreationClient(config),
    bindOperation: (operationConfig) =>
      createDesktopNewThreadCreationClient(Object.freeze({ ...operationConfig })),
  });
}

function createDesktopNewThreadCreationClient(
  config: DesktopRuntimeConfig,
): DesktopNewThreadCreationClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    createAgentConversation: (
      ...args: Parameters<DesktopApiClient['createAgentConversation']>
    ) => authority.createAgentConversation(...args),
    createTaskSession: (...args: Parameters<DesktopApiClient['createTaskSession']>) =>
      authority.createTaskSession(...args),
    runAgentMessage: (...args: Parameters<DesktopApiClient['runAgentMessage']>) =>
      authority.runAgentMessage(...args),
  });
}
