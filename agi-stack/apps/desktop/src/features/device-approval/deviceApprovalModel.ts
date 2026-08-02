const DEVICE_APPROVAL_CODE_LENGTH = 8;

export function normalizeDeviceApprovalCode(raw: string): string {
  let normalized = '';
  for (const character of raw) {
    const upper = character.toUpperCase();
    const code = upper.charCodeAt(0);
    const alphanumeric =
      (code >= 48 && code <= 57) || (code >= 65 && code <= 90);
    if (!alphanumeric) continue;
    normalized += upper;
    if (normalized.length === DEVICE_APPROVAL_CODE_LENGTH) break;
  }
  return normalized;
}

export function isCompleteDeviceApprovalCode(code: string): boolean {
  if (code.length !== DEVICE_APPROVAL_CODE_LENGTH) return false;
  return normalizeDeviceApprovalCode(code) === code;
}

export function readDeviceApprovalCodeFromHash(hash: string): string {
  const location = hash.trim();
  const hashIndex = location.indexOf('#');
  const raw = hashIndex >= 0 ? location.slice(hashIndex + 1) : location;
  if (!validPercentEncoding(raw)) return '';
  try {
    const url = new URL(raw.startsWith('/') ? raw : `/${raw}`, 'https://desktop.invalid');
    if (url.pathname !== '/device') return '';
    const userCodes = url.searchParams.getAll('user_code');
    const aliases = url.searchParams.getAll('code');
    if (
      userCodes.length > 1 ||
      aliases.length > 1 ||
      (userCodes.length === 1 && aliases.length === 1)
    ) {
      return '';
    }
    return normalizeDeviceApprovalCode(userCodes[0] ?? aliases[0] ?? '');
  } catch {
    return '';
  }
}

function validPercentEncoding(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    if (value[index] !== '%') continue;
    if (
      index + 2 >= value.length ||
      !isHex(value[index + 1]) ||
      !isHex(value[index + 2])
    ) {
      return false;
    }
    index += 2;
  }
  return true;
}

function isHex(character: string): boolean {
  const code = character.charCodeAt(0);
  return (
    (code >= 48 && code <= 57) ||
    (code >= 65 && code <= 70) ||
    (code >= 97 && code <= 102)
  );
}
