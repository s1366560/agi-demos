import { realpath, stat } from 'node:fs/promises';
import { isAbsolute, relative, resolve, sep } from 'node:path';

export const RENDERER_PROTOCOL_SCHEME = 'agistack';
export const RENDERER_PROTOCOL_HOST = 'app';
export const RENDERER_ENTRY_URL =
  `${RENDERER_PROTOCOL_SCHEME}://${RENDERER_PROTOCOL_HOST}/index.html`;

export class RendererProtocolError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'RendererProtocolError';
    this.status = status;
  }
}

function pathStaysWithin(root: string, target: string): boolean {
  const relativePath = relative(root, target);
  return (
    relativePath === '' ||
    (!relativePath.startsWith(`..${sep}`) &&
      relativePath !== '..' &&
      !isAbsolute(relativePath))
  );
}

function requestedAssetPath(requestUrl: string): string {
  let url: URL;
  try {
    url = new URL(requestUrl);
  } catch {
    throw new RendererProtocolError(400, 'renderer URL is invalid');
  }
  if (
    url.protocol !== `${RENDERER_PROTOCOL_SCHEME}:` ||
    url.hostname !== RENDERER_PROTOCOL_HOST ||
    url.username ||
    url.password ||
    url.port ||
    url.search ||
    url.hash
  ) {
    throw new RendererProtocolError(403, 'renderer URL is outside the application origin');
  }

  let decodedPath: string;
  try {
    decodedPath = decodeURIComponent(url.pathname);
  } catch {
    throw new RendererProtocolError(400, 'renderer URL encoding is invalid');
  }
  if (decodedPath.includes('\0') || decodedPath.includes('\\')) {
    throw new RendererProtocolError(403, 'renderer path is invalid');
  }

  return decodedPath === '/' ? 'index.html' : decodedPath.replace(/^\/+/u, '');
}

export async function resolveRendererAsset(
  rendererRoot: string,
  requestUrl: string,
): Promise<string> {
  const canonicalRoot = await realpath(rendererRoot).catch(() => {
    throw new RendererProtocolError(500, 'renderer root is unavailable');
  });
  const candidate = resolve(canonicalRoot, requestedAssetPath(requestUrl));
  if (!pathStaysWithin(canonicalRoot, candidate)) {
    throw new RendererProtocolError(403, 'renderer path escapes the application root');
  }

  const canonicalCandidate = await realpath(candidate).catch(() => {
    throw new RendererProtocolError(404, 'renderer asset was not found');
  });
  if (!pathStaysWithin(canonicalRoot, canonicalCandidate)) {
    throw new RendererProtocolError(403, 'renderer asset resolves outside the application root');
  }
  const assetStat = await stat(canonicalCandidate).catch(() => {
    throw new RendererProtocolError(404, 'renderer asset was not found');
  });
  if (!assetStat.isFile()) {
    throw new RendererProtocolError(404, 'renderer asset was not found');
  }
  return canonicalCandidate;
}
