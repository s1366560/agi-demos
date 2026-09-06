export const PLUGIN_DATA_PLANE_CREDENTIAL_ENV_V2 =
  'AGISTACK_PLUGIN_DATA_PLANE_CREDENTIAL_V2';
export const PLUGIN_DATA_PLANE_API_BASE_URL_ENV_V2 =
  'AGISTACK_PLUGIN_DATA_PLANE_API_BASE_URL_V2';
export const PLUGIN_DATA_PLANE_ACK_PARTICIPATION_ENV_V2 =
  'AGISTACK_PLUGIN_DATA_PLANE_ACK_PARTICIPATION_V2';

const DATA_PLANE_ID_V2 = 'desktop-sidecar-v2';
const CREDENTIAL_PATTERN_V2 = /^ms_dp_[a-f0-9]{64}$/u;

export type PlatformPluginDataPlaneCredentialRecordV2 = Readonly<{
  version: 2;
  api_base_url: string;
  data_plane_id: typeof DATA_PLANE_ID_V2;
  credential: string;
  ack_participation: boolean;
}>;

export function takePlatformPluginDataPlaneCredentialEnvironmentV2(
  environment: Record<string, string | undefined>,
): PlatformPluginDataPlaneCredentialRecordV2 | null {
  const credential = environment[PLUGIN_DATA_PLANE_CREDENTIAL_ENV_V2];
  const apiBaseUrl = environment[PLUGIN_DATA_PLANE_API_BASE_URL_ENV_V2];
  const ackParticipation = environment[PLUGIN_DATA_PLANE_ACK_PARTICIPATION_ENV_V2];
  delete environment[PLUGIN_DATA_PLANE_CREDENTIAL_ENV_V2];
  delete environment[PLUGIN_DATA_PLANE_API_BASE_URL_ENV_V2];
  delete environment[PLUGIN_DATA_PLANE_ACK_PARTICIPATION_ENV_V2];

  if (credential === undefined && apiBaseUrl === undefined && ackParticipation === undefined) {
    return null;
  }
  if (!credential || !apiBaseUrl || !CREDENTIAL_PATTERN_V2.test(credential)) {
    throw new Error('plugin data-plane credential environment is invalid');
  }
  validateControlPlaneBaseUrlV2(apiBaseUrl);
  if (
    ackParticipation !== undefined &&
    ackParticipation !== 'true' &&
    ackParticipation !== 'false'
  ) {
    throw new Error('plugin data-plane credential environment is invalid');
  }
  return Object.freeze({
    version: 2,
    api_base_url: apiBaseUrl,
    data_plane_id: DATA_PLANE_ID_V2,
    credential,
    ack_participation: ackParticipation === 'true',
  });
}

function validateControlPlaneBaseUrlV2(value: string): void {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error('plugin data-plane credential environment is invalid');
  }
  const isLoopback =
    url.hostname === '127.0.0.1' || url.hostname === 'localhost' || url.hostname === '[::1]';
  if (
    (url.protocol !== 'https:' && !(url.protocol === 'http:' && isLoopback)) ||
    url.username !== '' ||
    url.password !== '' ||
    url.search !== '' ||
    url.hash !== ''
  ) {
    throw new Error('plugin data-plane credential environment is invalid');
  }
}

export const PLUGIN_RENDERER_DATA_PLANE_CREDENTIAL_ENV_V2 =
  'AGISTACK_PLUGIN_RENDERER_DATA_PLANE_CREDENTIAL_V2';
export const PLUGIN_RENDERER_DATA_PLANE_API_BASE_URL_ENV_V2 =
  'AGISTACK_PLUGIN_RENDERER_DATA_PLANE_API_BASE_URL_V2';
export const PLUGIN_RENDERER_DATA_PLANE_ACK_PARTICIPATION_ENV_V2 =
  'AGISTACK_PLUGIN_RENDERER_DATA_PLANE_ACK_PARTICIPATION_V2';

export type PlatformPluginRendererCredentialRecordV2 = Readonly<
  Omit<PlatformPluginDataPlaneCredentialRecordV2, 'data_plane_id'> & {
    data_plane_id: 'desktop-renderer-v2';
  }
>;

export function takePlatformPluginCredentialEnvironmentsV2(
  environment: Record<string, string | undefined>,
): Readonly<{
  sidecar: PlatformPluginDataPlaneCredentialRecordV2 | null;
  renderer: PlatformPluginRendererCredentialRecordV2 | null;
}> {
  const take = (names: readonly string[]): Record<string, string | undefined> => {
    const values: Record<string, string | undefined> = {};
    for (const name of names) {
      values[name] = environment[name];
      delete environment[name];
    }
    return values;
  };
  // Consume both grants before validating either so startup failures leave no grant behind.
  const sidecarEnvironment = take([
    PLUGIN_DATA_PLANE_CREDENTIAL_ENV_V2,
    PLUGIN_DATA_PLANE_API_BASE_URL_ENV_V2,
    PLUGIN_DATA_PLANE_ACK_PARTICIPATION_ENV_V2,
  ]);
  const rendererEnvironment = take([
    PLUGIN_RENDERER_DATA_PLANE_CREDENTIAL_ENV_V2,
    PLUGIN_RENDERER_DATA_PLANE_API_BASE_URL_ENV_V2,
    PLUGIN_RENDERER_DATA_PLANE_ACK_PARTICIPATION_ENV_V2,
  ]);
  const sidecar = takePlatformPluginDataPlaneCredentialEnvironmentV2(sidecarEnvironment);
  const rendererGrant = takePlatformPluginDataPlaneCredentialEnvironmentV2({
    [PLUGIN_DATA_PLANE_CREDENTIAL_ENV_V2]:
      rendererEnvironment[PLUGIN_RENDERER_DATA_PLANE_CREDENTIAL_ENV_V2],
    [PLUGIN_DATA_PLANE_API_BASE_URL_ENV_V2]:
      rendererEnvironment[PLUGIN_RENDERER_DATA_PLANE_API_BASE_URL_ENV_V2],
    [PLUGIN_DATA_PLANE_ACK_PARTICIPATION_ENV_V2]:
      rendererEnvironment[PLUGIN_RENDERER_DATA_PLANE_ACK_PARTICIPATION_ENV_V2],
  });
  return Object.freeze({
    sidecar,
    renderer: rendererGrant === null
      ? null
      : Object.freeze({ ...rendererGrant, data_plane_id: 'desktop-renderer-v2' as const }),
  });
}
