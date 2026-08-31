import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopSessionArtifactActionMethod =
  | 'reviewArtifactVersion'
  | 'deliverArtifactVersion';

export type DesktopSessionArtifactActionClient = Readonly<
  Pick<DesktopApiClient, DesktopSessionArtifactActionMethod>
>;

export type DesktopSessionArtifactActionClientProviderReasonCodeV2 =
  'desktop_session_artifact_action_client_unpublished';

export class DesktopSessionArtifactActionClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopSessionArtifactActionClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopSessionArtifactActionClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopSessionArtifactActionClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopSessionArtifactActionClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopSessionArtifactActionClientBindingV2 = Readonly<{
  client: DesktopSessionArtifactActionClient;
  bindOperation: (config: DesktopRuntimeConfig) => DesktopSessionArtifactActionClient;
}>;

export type DesktopSessionArtifactActionClientProviderV2 = Readonly<{
  publish: (
    input: DesktopSessionArtifactActionClientProviderInputV2,
  ) => DesktopSessionArtifactActionClientBindingV2;
  resolve: () => DesktopSessionArtifactActionClientBindingV2;
}>;

export function createDesktopSessionArtifactActionClientProviderV2():
  DesktopSessionArtifactActionClientProviderV2 {
  let publication: DesktopSessionArtifactActionClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopSessionArtifactActionClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopSessionArtifactActionClientProviderErrorV2(
          'desktop_session_artifact_action_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopSessionArtifactActionClientBindingV2(
  input: DesktopSessionArtifactActionClientProviderInputV2,
): DesktopSessionArtifactActionClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopSessionArtifactActionClient(config),
    bindOperation: (operationConfig) =>
      createDesktopSessionArtifactActionClient(Object.freeze({ ...operationConfig })),
  });
}

function createDesktopSessionArtifactActionClient(
  config: DesktopRuntimeConfig,
): DesktopSessionArtifactActionClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    reviewArtifactVersion: (
      ...args: Parameters<DesktopApiClient['reviewArtifactVersion']>
    ) => authority.reviewArtifactVersion(...args),
    deliverArtifactVersion: (
      ...args: Parameters<DesktopApiClient['deliverArtifactVersion']>
    ) => authority.deliverArtifactVersion(...args),
  });
}
