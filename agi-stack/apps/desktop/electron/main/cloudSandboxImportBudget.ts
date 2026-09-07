import { authorizeCloudProductEndpoint } from './cloudProductEndpointPolicy';

const MAX_IMPORT_BYTES = 16 * 1024 * 1024;
const MAX_IMPORT_BASE64_CHARACTERS = 4 * Math.ceil(MAX_IMPORT_BYTES / 3);
const MAX_IMPORT_JSON_BYTES = MAX_IMPORT_BASE64_CHARACTERS + 4096;

// This grants only a body-size exception. Normal trusted-session loading,
// observed project scope enforcement and endpoint authorization still follow.
export function allowsCloudSandboxImportBudget(
  request: Readonly<Record<string, unknown>>,
  body: Readonly<Record<string, unknown>>,
  bodyBytes: number,
): boolean {
  if (
    bodyBytes > MAX_IMPORT_JSON_BYTES ||
    request.method !== 'POST' ||
    request.form !== undefined ||
    request.response !== undefined ||
    request.mutation !== undefined ||
    typeof request.path !== 'string'
  )
    return false;
  const target = new URL(request.path, 'https://desktop.invalid');
  const segments = target.pathname.split('/');
  if (
    target.origin !== 'https://desktop.invalid' ||
    target.search ||
    target.hash ||
    segments.length !== 7 ||
    segments[1] !== 'api' ||
    segments[2] !== 'v1' ||
    segments[3] !== 'projects' ||
    !segments[4] ||
    segments[5] !== 'sandbox' ||
    segments[6] !== 'execute'
  )
    return false;
  if (
    !exactKeys(body, ['tool_name', 'arguments', 'timeout']) ||
    body.tool_name !== 'import_file' ||
    !Number.isInteger(body.timeout) ||
    Number(body.timeout) < 60 ||
    Number(body.timeout) > 300
  )
    return false;
  const args = body.arguments;
  if (
    !record(args) ||
    !exactKeys(args, ['filename', 'content_base64', 'destination', 'overwrite']) ||
    args.destination !== '/workspace/input' ||
    args.overwrite !== true ||
    typeof args.filename !== 'string' ||
    !args.filename ||
    args.filename.length > 255 ||
    args.filename === '.' ||
    args.filename === '..' ||
    /[\/\\\u0000-\u001f\u007f]/u.test(args.filename)
  )
    return false;
  const encoded = args.content_base64;
  if (
    typeof encoded !== 'string' ||
    encoded.length > MAX_IMPORT_BASE64_CHARACTERS ||
    encoded.length % 4 !== 0
  )
    return false;
  // Node's decoder tolerates malformed input; canonical round-trip validation does not.
  const bytes = Buffer.from(encoded, 'base64');
  if (bytes.length > MAX_IMPORT_BYTES || bytes.toString('base64') !== encoded) return false;
  return authorizeCloudProductEndpoint({ method: 'POST', body }, target) !== null;
}
function record(value: unknown): value is Readonly<Record<string, unknown>> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function exactKeys(value: Readonly<Record<string, unknown>>, keys: readonly string[]): boolean {
  return (
    Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key))
  );
}
