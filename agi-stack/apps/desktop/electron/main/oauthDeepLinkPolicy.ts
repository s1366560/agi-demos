export const OAUTH_CALLBACK_SCHEME = 'agistack-auth';

export type OAuthCallbackDeepLink =
  | Readonly<{
      kind: 'success';
      provider: string;
      code: string;
      state: string;
    }>
  | Readonly<{
      kind: 'provider_error';
      provider: string;
      error: string;
      errorDescription: string | null;
      state: string;
    }>;

export type OAuthDeepLinkReasonCode =
  | 'oauth_deep_link_invalid'
  | 'oauth_deep_link_ambiguous';

export class OAuthDeepLinkPolicyError extends Error {
  readonly reasonCode: OAuthDeepLinkReasonCode;

  constructor(reasonCode: OAuthDeepLinkReasonCode) {
    super(reasonCode);
    this.name = 'OAuthDeepLinkPolicyError';
    this.reasonCode = reasonCode;
  }
}

const PROVIDER_ID = /^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$/u;
const OAUTH_ERROR = /^[a-z0-9](?:[a-z0-9_.-]{0,126}[a-z0-9])?$/u;
const OAUTH_STATE = /^[A-Za-z0-9_-]{43}$/u;
const SUCCESS_QUERY_KEYS = new Set(['code', 'state']);
const ERROR_QUERY_KEYS = new Set(['error', 'error_description', 'state']);
const MAX_CODE_BYTES = 4096;
const MAX_ERROR_DESCRIPTION_BYTES = 512;

export function parseOAuthCallbackDeepLink(raw: string): OAuthCallbackDeepLink {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw invalidDeepLink();
  }
  if (
    url.protocol !== `${OAUTH_CALLBACK_SCHEME}:` ||
    url.hostname !== 'oauth' ||
    url.username ||
    url.password ||
    url.port ||
    url.hash
  ) {
    throw invalidDeepLink();
  }
  const pathSegments = url.pathname.split('/');
  const provider = pathSegments[2];
  if (
    pathSegments.length !== 3 ||
    pathSegments[0] !== '' ||
    pathSegments[1] !== 'callback' ||
    !provider ||
    !PROVIDER_ID.test(provider)
  ) {
    throw invalidDeepLink();
  }
  const state = singleQueryValue(url.searchParams, 'state');
  if (!state || !OAUTH_STATE.test(state)) throw invalidDeepLink();

  const code = singleQueryValue(url.searchParams, 'code');
  const error = singleQueryValue(url.searchParams, 'error');
  if (code !== null && error === null) {
    assertExactQuery(url.searchParams, SUCCESS_QUERY_KEYS);
    if (!boundedOpaqueValue(code, MAX_CODE_BYTES)) throw invalidDeepLink();
    return Object.freeze({ kind: 'success', provider, code, state });
  }
  if (error !== null && code === null) {
    assertExactQuery(url.searchParams, ERROR_QUERY_KEYS, true);
    if (!OAUTH_ERROR.test(error)) throw invalidDeepLink();
    const description = singleQueryValue(url.searchParams, 'error_description');
    if (
      description !== null &&
      (!boundedText(description, MAX_ERROR_DESCRIPTION_BYTES) || description.length === 0)
    ) {
      throw invalidDeepLink();
    }
    return Object.freeze({
      kind: 'provider_error',
      provider,
      error,
      errorDescription: description,
      state,
    });
  }
  throw invalidDeepLink();
}

export function selectOAuthDeepLinkFromArgv(
  argv: readonly string[],
): OAuthCallbackDeepLink | null {
  const candidates = argv.filter(
    (argument) =>
      typeof argument === 'string' &&
      argument.toLowerCase().startsWith(`${OAUTH_CALLBACK_SCHEME}:`),
  );
  if (candidates.length === 0) return null;
  if (candidates.length !== 1) {
    throw new OAuthDeepLinkPolicyError('oauth_deep_link_ambiguous');
  }
  return parseOAuthCallbackDeepLink(candidates[0]);
}

function assertExactQuery(
  query: URLSearchParams,
  keys: ReadonlySet<string>,
  optionalDescription = false,
): void {
  const entries = [...query.entries()];
  if (
    entries.some(([key]) => !keys.has(key)) ||
    [...keys].some(
      (key) =>
        !(optionalDescription && key === 'error_description') && query.getAll(key).length !== 1,
    ) ||
    (optionalDescription && query.getAll('error_description').length > 1)
  ) {
    throw invalidDeepLink();
  }
}

function singleQueryValue(query: URLSearchParams, key: string): string | null {
  const values = query.getAll(key);
  return values.length === 1 ? values[0] : null;
}

function boundedOpaqueValue(value: string, maxBytes: number): boolean {
  return (
    value.length > 0 &&
    value === value.trim() &&
    !hasControlCharacter(value) &&
    new TextEncoder().encode(value).byteLength <= maxBytes
  );
}

function boundedText(value: string, maxBytes: number): boolean {
  return (
    !hasControlCharacter(value) && new TextEncoder().encode(value).byteLength <= maxBytes
  );
}

function hasControlCharacter(value: string): boolean {
  return [...value].some((character) => {
    const code = character.charCodeAt(0);
    return code <= 0x1f || code === 0x7f;
  });
}

function invalidDeepLink(): OAuthDeepLinkPolicyError {
  return new OAuthDeepLinkPolicyError('oauth_deep_link_invalid');
}
