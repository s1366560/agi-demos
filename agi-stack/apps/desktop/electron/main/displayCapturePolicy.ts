export const MAX_CAPTURE_PNG_BYTES = 8 * 1024 * 1024;
export const MAX_CAPTURE_DIMENSION = 2560;

const PNG_SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10] as const;

export type DisplayCaptureSource<T> = {
  displayId: string;
  value: T;
};

export type DesktopDisplayCapture = {
  dataUrl: string;
  displayId: string;
  height: number;
  mimeType: 'image/png';
  pngBytes: number;
  width: number;
};

export type DisplayCaptureAuthorization = Readonly<{
  expiresAtMs: number;
  token: symbol;
}>;

export class DisplayCaptureAuthorizationGate {
  readonly #activeTokens = new Set<symbol>();
  readonly #grantLifetimeMs: number;

  constructor({ grantLifetimeMs = 15_000 }: { grantLifetimeMs?: number } = {}) {
    if (!Number.isSafeInteger(grantLifetimeMs) || grantLifetimeMs <= 0) {
      throw new Error('display capture authorization lifetime is invalid');
    }
    this.#grantLifetimeMs = grantLifetimeMs;
  }

  async authorize(
    confirm: () => Promise<boolean>,
    now: () => number = Date.now,
  ): Promise<DisplayCaptureAuthorization> {
    if ((await confirm()) !== true) {
      throw new Error('display capture was not authorized');
    }
    const issuedAtMs = now();
    if (!Number.isSafeInteger(issuedAtMs) || issuedAtMs < 0) {
      throw new Error('display capture authorization clock is invalid');
    }
    const token = Symbol('display-capture-authorization');
    this.#activeTokens.add(token);
    return Object.freeze({
      expiresAtMs: issuedAtMs + this.#grantLifetimeMs,
      token,
    });
  }

  consume(
    authorization: DisplayCaptureAuthorization,
    now: () => number = Date.now,
  ): void {
    if (
      !authorization ||
      typeof authorization.token !== 'symbol' ||
      !this.#activeTokens.delete(authorization.token)
    ) {
      throw new Error('display capture authorization is invalid or already used');
    }
    if (now() > authorization.expiresAtMs) {
      throw new Error('display capture authorization has expired');
    }
  }
}

export function captureThumbnailSize(
  logicalWidth: number,
  logicalHeight: number,
  scaleFactor: number,
): { width: number; height: number } {
  if (
    !Number.isFinite(logicalWidth) ||
    !Number.isFinite(logicalHeight) ||
    !Number.isFinite(scaleFactor) ||
    logicalWidth <= 0 ||
    logicalHeight <= 0 ||
    scaleFactor <= 0
  ) {
    throw new Error('display capture dimensions are invalid');
  }
  const nativeWidth = logicalWidth * scaleFactor;
  const nativeHeight = logicalHeight * scaleFactor;
  const ratio = Math.min(1, MAX_CAPTURE_DIMENSION / Math.max(nativeWidth, nativeHeight));
  return {
    width: Math.max(1, Math.round(nativeWidth * ratio)),
    height: Math.max(1, Math.round(nativeHeight * ratio)),
  };
}

export function selectExactDisplaySource<T>(
  sources: readonly DisplayCaptureSource<T>[],
  targetDisplayId: string,
): DisplayCaptureSource<T> {
  const matches = sources.filter((source) => source.displayId === targetDisplayId);
  if (matches.length !== 1) {
    throw new Error('exact display capture source is unavailable');
  }
  return matches[0] as DisplayCaptureSource<T>;
}

export function assertPngCaptureWithinLimit(
  png: Uint8Array,
  maxBytes: number = MAX_CAPTURE_PNG_BYTES,
): number {
  if (
    png.byteLength < PNG_SIGNATURE.length ||
    PNG_SIGNATURE.some((byte, index) => png[index] !== byte)
  ) {
    throw new Error('display capture is not a PNG');
  }
  if (!Number.isSafeInteger(maxBytes) || maxBytes <= 0 || png.byteLength > maxBytes) {
    throw new Error('display capture PNG exceeds the allowed size');
  }
  return png.byteLength;
}
