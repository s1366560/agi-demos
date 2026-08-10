import { desktopApiCredential, desktopLaunchCapability } from '../../api/client';
import { desktopApiFetch } from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';
import { readArtifactContentContractV2 } from './artifactContentContractV2';

export type ArtifactContentContractV2 = {
  contract_version: 2;
  artifact_id: string;
  revision: number;
  content_hash: string;
  mime_type: string;
  content: string;
};

export type ArtifactSaveCommandV2 = {
  contract_version: 2;
  expected_revision: number;
  content_hash: string;
  idempotency_key: string;
  content: string;
};

export type ArtifactSaveReceipt = {
  artifact_id: string;
  revision: number;
  content_hash: string;
  duplicate: boolean;
};

export type DesktopArtifactClient = {
  loadContent(artifactId: string, signal?: AbortSignal): Promise<ArtifactContentContractV2>;
  saveContent(
    artifactId: string,
    command: ArtifactSaveCommandV2,
    signal?: AbortSignal,
  ): Promise<ArtifactSaveReceipt>;
  download(artifactId: string, signal?: AbortSignal): Promise<Blob>;
};

export class DesktopArtifactRequestError extends Error {
  readonly httpStatus: number | null;
  readonly reasonCode: string;
  readonly serverRevision: number | null;
  readonly serverContentHash: string | null;

  constructor(input: {
    reasonCode: string;
    httpStatus?: number | null;
    serverRevision?: number | null;
    serverContentHash?: string | null;
  }) {
    super(input.reasonCode);
    this.name = 'DesktopArtifactRequestError';
    this.reasonCode = input.reasonCode;
    this.httpStatus = input.httpStatus ?? null;
    this.serverRevision = input.serverRevision ?? null;
    this.serverContentHash = input.serverContentHash ?? null;
  }
}

export function createDesktopArtifactClient(
  authority: DesktopArtifactClient,
): DesktopArtifactClient {
  return Object.freeze({
    loadContent: (artifactId: string, signal?: AbortSignal) =>
      authority.loadContent(artifactId, signal),
    saveContent: (
      artifactId: string,
      command: ArtifactSaveCommandV2,
      signal?: AbortSignal,
    ) => authority.saveContent(artifactId, command, signal),
    download: (artifactId: string, signal?: AbortSignal) =>
      authority.download(artifactId, signal),
  });
}

export function createHttpDesktopArtifactClient(
  config: DesktopRuntimeConfig,
): DesktopArtifactClient {
  const runtimeConfig = Object.freeze({ ...config });
  return createDesktopArtifactClient({
    async loadContent(artifactId, signal) {
      const payload = await requestArtifactJson(
        runtimeConfig,
        artifactPath(artifactId, '/content'),
        { signal },
      );
      const result = readArtifactContentContractV2(payload);
      if (!result.ok || result.value.artifact_id !== artifactId.trim()) {
        throw new DesktopArtifactRequestError({
          reasonCode: 'artifact_content_contract_invalid',
        });
      }
      return result.value;
    },
    async saveContent(artifactId, command, signal) {
      const payload = await requestArtifactJson(
        runtimeConfig,
        artifactPath(artifactId, '/content'),
        {
          method: 'PUT',
          body: command,
          signal,
        },
      );
      return readSaveReceipt(payload, artifactId, command);
    },
    async download(artifactId, signal) {
      const response = await requestArtifact(
        runtimeConfig,
        artifactPath(artifactId, '/content/bytes'),
        { signal },
      );
      return response.blob();
    },
  });
}

type ArtifactRequestOptions = {
  method?: 'GET' | 'PUT';
  body?: ArtifactSaveCommandV2;
  signal?: AbortSignal;
};

async function requestArtifactJson(
  config: DesktopRuntimeConfig,
  path: string,
  options: ArtifactRequestOptions,
): Promise<unknown> {
  const response = await requestArtifact(config, path, options);
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.toLowerCase().includes('application/json')) {
    throw new DesktopArtifactRequestError({
      reasonCode: 'artifact_response_contract_invalid',
      httpStatus: response.status,
    });
  }
  return response.json().catch(() => {
    throw new DesktopArtifactRequestError({
      reasonCode: 'artifact_response_contract_invalid',
      httpStatus: response.status,
    });
  });
}

async function requestArtifact(
  config: DesktopRuntimeConfig,
  path: string,
  options: ArtifactRequestOptions,
): Promise<Response> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  if (options.body) {
    headers.set('Content-Type', 'application/json');
    headers.set('X-Expected-Revision', String(options.body.expected_revision));
    headers.set('Idempotency-Key', options.body.idempotency_key);
  }
  if (path.endsWith('/content/bytes')) {
    headers.set('Accept', '*/*');
  }

  const response = await desktopApiFetch(
    config,
    path,
    {
      method: options.method ?? 'GET',
      headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
      redirect: 'follow',
    },
    path.endsWith('/content/bytes')
      ? { responseType: 'binary', maxBytes: 16 * 1024 * 1024 }
      : undefined,
  );
  if (response.ok) return response;

  const payload = await readErrorPayload(response);
  throw new DesktopArtifactRequestError({
    reasonCode:
      typeof payload?.reason_code === 'string' && payload.reason_code.trim()
        ? payload.reason_code
        : 'artifact_request_failed',
    httpStatus: response.status,
    serverRevision:
      Number.isSafeInteger(payload?.server_revision) && Number(payload?.server_revision) >= 0
        ? Number(payload?.server_revision)
        : null,
    serverContentHash:
      typeof payload?.server_content_hash === 'string'
        ? payload.server_content_hash
        : null,
  });
}

function artifactPath(artifactId: string, suffix: string): string {
  const normalized = artifactId.trim();
  if (!normalized || normalized.length > 256) {
    throw new DesktopArtifactRequestError({ reasonCode: 'artifact_id_invalid' });
  }
  return `/api/v1/artifacts/${encodeURIComponent(normalized)}${suffix}`;
}

function readSaveReceipt(
  payload: unknown,
  artifactId: string,
  command: ArtifactSaveCommandV2,
): ArtifactSaveReceipt {
  if (!isRecord(payload)) {
    throw new DesktopArtifactRequestError({
      reasonCode: 'artifact_save_receipt_invalid',
    });
  }
  const revision = payload.revision;
  const contentHash = payload.content_hash;
  if (
    payload.artifact_id !== artifactId.trim() ||
    !Number.isSafeInteger(revision) ||
    Number(revision) < command.expected_revision ||
    typeof contentHash !== 'string' ||
    contentHash !== command.content_hash ||
    typeof payload.duplicate !== 'boolean'
  ) {
    throw new DesktopArtifactRequestError({
      reasonCode: 'artifact_save_receipt_invalid',
    });
  }
  return {
    artifact_id: payload.artifact_id,
    revision: Number(revision),
    content_hash: contentHash,
    duplicate: payload.duplicate,
  };
}

async function readErrorPayload(response: Response): Promise<Record<string, unknown> | null> {
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.toLowerCase().includes('application/json')) return null;
  const payload: unknown = await response.json().catch(() => null);
  if (!isRecord(payload)) return null;
  if (isRecord(payload.detail)) return payload.detail;
  return payload;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
