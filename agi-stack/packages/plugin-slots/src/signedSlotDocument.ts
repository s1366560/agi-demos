import { parseSlotUi } from './signedSlotUi';

export interface SignedSlotResourceV2 {
  readonly moduleRef: string;
  readonly digest: string;
  readonly source: string;
  readonly target: 'web' | 'desktop-renderer';
  readonly bytes: Uint8Array;
}

const ALLOWED_SOURCE_PREFIXES = ['bundle://', 'marketplace://', 'signed-package://'];

/** Load signed slot bytes into a sandboxed document. A signed: prefix alone is not enough. */
export async function createVerifiedSignedSlotDocumentV2(
  resource: SignedSlotResourceV2,
  nonce: string
): Promise<string | null> {
  if (!resource.moduleRef.startsWith('signed:')) return null;
  if (!ALLOWED_SOURCE_PREFIXES.some((prefix) => resource.source.startsWith(prefix))) return null;
  if (resource.target !== 'web' && resource.target !== 'desktop-renderer') return null;
  const digest = await sha256(resource.bytes);
  if (digest !== resource.digest) return null;
  let parsed: ReturnType<typeof parseSlotUi>;
  try {
    parsed = parseSlotUi(JSON.parse(new TextDecoder().decode(resource.bytes)));
  } catch {
    return null;
  }
  const actions = parsed.actions
    .map(
      (action) =>
        `<button type="button" data-action="${escapeAttribute(action.id)}">${escapeText(action.label)}</button>`
    )
    .join('');
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-${nonce}'; style-src 'nonce-${nonce}'"><style nonce="${nonce}">body{font:13px system-ui}</style></head><body><h1>${escapeText(parsed.title)}</h1><nav>${actions}</nav><script nonce="${nonce}">document.querySelectorAll('button').forEach((node)=>{node.addEventListener('click',()=>{parent.postMessage({source:'memstack-plugin-slot-v2',type:'slot:action',action:{type:'plugin.ui',id:node.dataset.action}},'*')})})</script></body></html>`;
}

async function sha256(bytes: Uint8Array): Promise<string> {
  const copy = new ArrayBuffer(bytes.byteLength);
  new Uint8Array(copy).set(bytes);
  const digest = await crypto.subtle.digest('SHA-256', copy);
  const hex = [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, '0')).join('');
  return `sha256:${hex}`;
}

function escapeText(value: string): string {
  return value.replace(/[&<>]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[character] ?? character);
}

function escapeAttribute(value: string): string {
  return escapeText(value).replace(/"/g, '&quot;');
}
