import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopSessionRunControlMethod =
  | 'pauseRun'
  | 'resumeRun'
  | 'forkRecoveryRun'
  | 'cancelRun'
  | 'reviewRun';

export type DesktopSessionRunControlClient = Readonly<
  Pick<DesktopApiClient, DesktopSessionRunControlMethod>
>;

export type DesktopSessionRunControlClientProviderReasonCodeV2 =
  'desktop_session_run_control_client_unpublished';

export class DesktopSessionRunControlClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopSessionRunControlClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopSessionRunControlClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopSessionRunControlClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopSessionRunControlClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopSessionRunControlClientBindingV2 = Readonly<{
  client: DesktopSessionRunControlClient;
  bindOperation: (config: DesktopRuntimeConfig) => DesktopSessionRunControlClient;
}>;

export type DesktopSessionRunControlClientProviderV2 = Readonly<{
  publish: (
    input: DesktopSessionRunControlClientProviderInputV2,
  ) => DesktopSessionRunControlClientBindingV2;
  resolve: () => DesktopSessionRunControlClientBindingV2;
}>;

export function createDesktopSessionRunControlClientProviderV2():
  DesktopSessionRunControlClientProviderV2 {
  let publication: DesktopSessionRunControlClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopSessionRunControlClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopSessionRunControlClientProviderErrorV2(
          'desktop_session_run_control_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopSessionRunControlClientBindingV2(
  input: DesktopSessionRunControlClientProviderInputV2,
): DesktopSessionRunControlClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopSessionRunControlClient(config),
    bindOperation: (operationConfig) =>
      createDesktopSessionRunControlClient(Object.freeze({ ...operationConfig })),
  });
}

function createDesktopSessionRunControlClient(
  config: DesktopRuntimeConfig,
): DesktopSessionRunControlClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    pauseRun: (...args: Parameters<DesktopApiClient['pauseRun']>) =>
      authority.pauseRun(...args),
    resumeRun: (...args: Parameters<DesktopApiClient['resumeRun']>) =>
      authority.resumeRun(...args),
    forkRecoveryRun: (...args: Parameters<DesktopApiClient['forkRecoveryRun']>) =>
      authority.forkRecoveryRun(...args),
    cancelRun: (...args: Parameters<DesktopApiClient['cancelRun']>) =>
      authority.cancelRun(...args),
    reviewRun: (...args: Parameters<DesktopApiClient['reviewRun']>) =>
      authority.reviewRun(...args),
  });
}
