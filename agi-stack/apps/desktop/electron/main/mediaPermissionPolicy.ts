export type TrustedAudioMediaPermissionRequest = {
  senderIsMainWindow: boolean;
  permission: string;
  requestingUrl: string;
  allowedOrigin: string;
  mediaTypes: readonly string[];
};

type PermissionOrigin = {
  protocol: string;
  hostname: string;
  port: string;
};

function permissionOrigin(value: string): PermissionOrigin | null {
  try {
    const url = new URL(value);
    if (url.username || url.password) return null;
    return {
      protocol: url.protocol.toLowerCase(),
      hostname: url.hostname.toLowerCase(),
      port: url.port,
    };
  } catch {
    return null;
  }
}

function samePermissionOrigin(left: string, right: string): boolean {
  const leftOrigin = permissionOrigin(left);
  const rightOrigin = permissionOrigin(right);
  return (
    leftOrigin !== null &&
    rightOrigin !== null &&
    leftOrigin.protocol === rightOrigin.protocol &&
    leftOrigin.hostname === rightOrigin.hostname &&
    leftOrigin.port === rightOrigin.port
  );
}

export function isTrustedAudioMediaPermission(
  request: TrustedAudioMediaPermissionRequest,
): boolean {
  return (
    request.senderIsMainWindow &&
    request.permission === 'media' &&
    request.mediaTypes.length === 1 &&
    request.mediaTypes[0] === 'audio' &&
    samePermissionOrigin(request.requestingUrl, request.allowedOrigin)
  );
}
