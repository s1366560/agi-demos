export type InvitationVerification = Readonly<{
  valid: true;
  email: string;
  tenant_id: string;
  role: string;
  expires_at: string;
}>;

export type AcceptedInvitation = Readonly<{
  id: string;
  tenant_id: string;
  email: string;
  role: string;
  status: string;
  invited_by: string;
  expires_at: string;
  created_at: string;
}>;

const MAX_INVITATION_TOKEN_LENGTH = 512;

export function readInvitationTokenFromHash(hash: string): string {
  const location = hash.trim();
  const hashIndex = location.indexOf('#');
  const raw = hashIndex >= 0 ? location.slice(hashIndex + 1) : location;
  if (!validPercentEncoding(raw)) return '';
  try {
    const url = new URL(raw.startsWith('/') ? raw : `/${raw}`, 'https://desktop.invalid');
    if (url.pathname !== '/invite') return '';
    const tokens = url.searchParams.getAll('token');
    if (tokens.length !== 1) return '';
    const token = tokens[0];
    if (
      token.length === 0 ||
      token.length > MAX_INVITATION_TOKEN_LENGTH ||
      hasControlCharacter(token)
    ) {
      return '';
    }
    return token;
  } catch {
    return '';
  }
}

export function invitationIsExpired(expiresAt: string, now = Date.now()): boolean {
  const expiry = Date.parse(expiresAt);
  return Number.isFinite(expiry) && expiry < now;
}

function hasControlCharacter(value: string): boolean {
  for (const character of value) {
    const code = character.charCodeAt(0);
    if (code < 32 || code === 127) return true;
  }
  return false;
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
