import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopHitlResponseMethod = 'respondToHitl';

export type DesktopHitlResponseClient = Readonly<
  Pick<DesktopApiClient, DesktopHitlResponseMethod>
>;

export type DesktopHitlResponseClientProviderReasonCodeV2 =
  'desktop_hitl_response_client_unpublished';

export class DesktopHitlResponseClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopHitlResponseClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopHitlResponseClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopHitlResponseClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopHitlResponseClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopHitlResponseClientBindingV2 = Readonly<{
  client: DesktopHitlResponseClient;
  bindOperation: (config: DesktopRuntimeConfig) => DesktopHitlResponseClient;
}>;

export type DesktopHitlResponseClientProviderV2 = Readonly<{
  publish: (
    input: DesktopHitlResponseClientProviderInputV2,
  ) => DesktopHitlResponseClientBindingV2;
  resolve: () => DesktopHitlResponseClientBindingV2;
}>;

export function createDesktopHitlResponseClientProviderV2():
  DesktopHitlResponseClientProviderV2 {
  let publication: DesktopHitlResponseClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopHitlResponseClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopHitlResponseClientProviderErrorV2(
          'desktop_hitl_response_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopHitlResponseClientBindingV2(
  input: DesktopHitlResponseClientProviderInputV2,
): DesktopHitlResponseClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopHitlResponseClient(config),
    bindOperation: (operationConfig) =>
      createDesktopHitlResponseClient(Object.freeze({ ...operationConfig })),
  });
}

function createDesktopHitlResponseClient(
  config: DesktopRuntimeConfig,
): DesktopHitlResponseClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    respondToHitl: (...args: Parameters<DesktopApiClient['respondToHitl']>) =>
      authority.respondToHitl(...args),
  });
}
