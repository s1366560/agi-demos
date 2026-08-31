import type { DesktopRuntimeConfig } from '../../types';
import {
  createHttpDesktopArtifactClient,
  type DesktopArtifactClient,
} from './desktopArtifactClient';

export type DesktopArtifactClientProviderReasonCodeV2 =
  'desktop_artifact_client_unpublished';

export class DesktopArtifactClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopArtifactClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopArtifactClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopArtifactClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopArtifactClientInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopArtifactClientBindingV2 = Readonly<{
  client: DesktopArtifactClient;
}>;

export type DesktopArtifactClientProviderV2 = Readonly<{
  publish: (input: DesktopArtifactClientInputV2) => DesktopArtifactClientBindingV2;
  resolve: () => DesktopArtifactClientBindingV2;
}>;

export function createDesktopArtifactClientProviderV2(): DesktopArtifactClientProviderV2 {
  let publication: DesktopArtifactClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopArtifactClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopArtifactClientProviderErrorV2(
          'desktop_artifact_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopArtifactClientBindingV2(
  input: DesktopArtifactClientInputV2,
): DesktopArtifactClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  const client = createHttpDesktopArtifactClient(config);
  return Object.freeze({ client });
}
