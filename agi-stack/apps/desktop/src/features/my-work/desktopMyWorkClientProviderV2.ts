import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopMyWorkMethod = 'listMyWork';

export type DesktopMyWorkClient = Readonly<Pick<DesktopApiClient, DesktopMyWorkMethod>>;

export type DesktopMyWorkClientProviderReasonCodeV2 =
  'desktop_my_work_client_unpublished';

export class DesktopMyWorkClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopMyWorkClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopMyWorkClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopMyWorkClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopMyWorkClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopMyWorkClientBindingV2 = Readonly<{
  client: DesktopMyWorkClient;
  bindOperation: (config: DesktopRuntimeConfig) => DesktopMyWorkClient;
}>;

export type DesktopMyWorkClientProviderV2 = Readonly<{
  publish: (input: DesktopMyWorkClientProviderInputV2) => DesktopMyWorkClientBindingV2;
  resolve: () => DesktopMyWorkClientBindingV2;
}>;

export function createDesktopMyWorkClientProviderV2(): DesktopMyWorkClientProviderV2 {
  let publication: DesktopMyWorkClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopMyWorkClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopMyWorkClientProviderErrorV2('desktop_my_work_client_unpublished');
      }
      return publication;
    },
  });
}

function createDesktopMyWorkClientBindingV2(
  input: DesktopMyWorkClientProviderInputV2,
): DesktopMyWorkClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopMyWorkClient(config),
    bindOperation: (operationConfig) =>
      createDesktopMyWorkClient(Object.freeze({ ...operationConfig })),
  });
}

function createDesktopMyWorkClient(config: DesktopRuntimeConfig): DesktopMyWorkClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    listMyWork: (...args: Parameters<DesktopApiClient['listMyWork']>) =>
      authority.listMyWork(...args),
  });
}
