import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopSessionRunInputMethod =
  | 'createRunInput'
  | 'listRunInputs'
  | 'promoteRunInput';

export type DesktopSessionRunInputClient = Readonly<
  Pick<DesktopApiClient, DesktopSessionRunInputMethod>
>;

export type DesktopSessionRunInputClientProviderReasonCodeV2 =
  'desktop_session_run_input_client_unpublished';

export class DesktopSessionRunInputClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopSessionRunInputClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopSessionRunInputClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopSessionRunInputClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopSessionRunInputClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopSessionRunInputClientBindingV2 = Readonly<{
  client: DesktopSessionRunInputClient;
  bindOperation: (config: DesktopRuntimeConfig) => DesktopSessionRunInputClient;
}>;

export type DesktopSessionRunInputClientProviderV2 = Readonly<{
  publish: (
    input: DesktopSessionRunInputClientProviderInputV2,
  ) => DesktopSessionRunInputClientBindingV2;
  resolve: () => DesktopSessionRunInputClientBindingV2;
}>;

export function createDesktopSessionRunInputClientProviderV2():
  DesktopSessionRunInputClientProviderV2 {
  let publication: DesktopSessionRunInputClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopSessionRunInputClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopSessionRunInputClientProviderErrorV2(
          'desktop_session_run_input_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopSessionRunInputClientBindingV2(
  input: DesktopSessionRunInputClientProviderInputV2,
): DesktopSessionRunInputClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopSessionRunInputClient(config),
    bindOperation: (operationConfig) =>
      createDesktopSessionRunInputClient(Object.freeze({ ...operationConfig })),
  });
}

function createDesktopSessionRunInputClient(
  config: DesktopRuntimeConfig,
): DesktopSessionRunInputClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    createRunInput: (...args: Parameters<DesktopApiClient['createRunInput']>) =>
      authority.createRunInput(...args),
    listRunInputs: (...args: Parameters<DesktopApiClient['listRunInputs']>) =>
      authority.listRunInputs(...args),
    promoteRunInput: (...args: Parameters<DesktopApiClient['promoteRunInput']>) =>
      authority.promoteRunInput(...args),
  });
}
