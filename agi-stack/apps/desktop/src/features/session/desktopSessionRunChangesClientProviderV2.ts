import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopSessionRunChangesMethod = 'getRunChanges';

export type DesktopSessionRunChangesClient = Readonly<
  Pick<DesktopApiClient, DesktopSessionRunChangesMethod>
>;

export type DesktopSessionRunChangesClientProviderReasonCodeV2 =
  'desktop_session_run_changes_client_unpublished';

export class DesktopSessionRunChangesClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopSessionRunChangesClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopSessionRunChangesClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopSessionRunChangesClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopSessionRunChangesClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopSessionRunChangesClientBindingV2 = Readonly<{
  client: DesktopSessionRunChangesClient;
  bindOperation: (config: DesktopRuntimeConfig) => DesktopSessionRunChangesClient;
}>;

export type DesktopSessionRunChangesClientProviderV2 = Readonly<{
  publish: (
    input: DesktopSessionRunChangesClientProviderInputV2,
  ) => DesktopSessionRunChangesClientBindingV2;
  resolve: () => DesktopSessionRunChangesClientBindingV2;
}>;

export function createDesktopSessionRunChangesClientProviderV2():
  DesktopSessionRunChangesClientProviderV2 {
  let publication: DesktopSessionRunChangesClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopSessionRunChangesClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopSessionRunChangesClientProviderErrorV2(
          'desktop_session_run_changes_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopSessionRunChangesClientBindingV2(
  input: DesktopSessionRunChangesClientProviderInputV2,
): DesktopSessionRunChangesClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopSessionRunChangesClient(config),
    bindOperation: (operationConfig) =>
      createDesktopSessionRunChangesClient(Object.freeze({ ...operationConfig })),
  });
}

function createDesktopSessionRunChangesClient(
  config: DesktopRuntimeConfig,
): DesktopSessionRunChangesClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    getRunChanges: (...args: Parameters<DesktopApiClient['getRunChanges']>) =>
      authority.getRunChanges(...args),
  });
}
