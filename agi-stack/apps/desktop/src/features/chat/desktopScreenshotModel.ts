const MAX_SCREENSHOT_BYTES = 8 * 1024 * 1024;
const PNG_DATA_URL_PREFIX = 'data:image/png;base64,';
const PNG_SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10] as const;

export type DesktopScreenshotPreview = {
  bytes: Uint8Array;
  dataUrl: string;
  displayId: string;
  height: number;
  width: number;
};

export function readDesktopScreenshotPreview(input: unknown): DesktopScreenshotPreview {
  if (
    !isRecord(input) ||
    input.mimeType !== 'image/png' ||
    typeof input.dataUrl !== 'string' ||
    !input.dataUrl.startsWith(PNG_DATA_URL_PREFIX) ||
    typeof input.displayId !== 'string' ||
    !input.displayId ||
    !isPositiveInteger(input.width) ||
    !isPositiveInteger(input.height) ||
    !isPositiveInteger(input.pngBytes) ||
    input.pngBytes > MAX_SCREENSHOT_BYTES
  ) {
    throw new Error('desktop screenshot preview is invalid');
  }
  const bytes = decodeBase64(input.dataUrl.slice(PNG_DATA_URL_PREFIX.length));
  if (
    bytes.byteLength !== input.pngBytes ||
    bytes.byteLength < PNG_SIGNATURE.length ||
    PNG_SIGNATURE.some((byte, index) => bytes[index] !== byte)
  ) {
    throw new Error('desktop screenshot preview is invalid');
  }
  return {
    bytes,
    dataUrl: input.dataUrl,
    displayId: input.displayId,
    height: input.height,
    width: input.width,
  };
}

export function desktopScreenshotFile(
  preview: DesktopScreenshotPreview,
  capturedAt: Date = new Date(),
): File {
  const fileBytes = new Uint8Array(preview.bytes.byteLength);
  fileBytes.set(preview.bytes);
  const timestamp = capturedAt
    .toISOString()
    .replaceAll(':', '-')
    .replaceAll('.', '-');
  return new File([fileBytes.buffer as ArrayBuffer], `memstack-screenshot-${timestamp}.png`, {
    type: 'image/png',
    lastModified: capturedAt.getTime(),
  });
}

function decodeBase64(value: string): Uint8Array {
  let binary: string;
  try {
    binary = atob(value);
  } catch {
    throw new Error('desktop screenshot preview is invalid');
  }
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
