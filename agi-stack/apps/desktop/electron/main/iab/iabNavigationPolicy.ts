/**
 * Navigation policy for in-app browser (iab) WebContentsViews.
 *
 * Mirrors the decision-function style of `webControlPlanePolicy.ts` /
 * `mediaPermissionPolicy.ts`: pure decisions, no Electron imports, so the
 * policy is unit-testable from the compiled dist. The view pool wires these
 * decisions onto each view's `webContents` (will-navigate, window-open,
 * permission handlers).
 */

/** Schemes an iab tab is allowed to display. */
export const IAB_ALLOWED_NAVIGATION_PROTOCOLS = Object.freeze([
  'http:',
  'https:',
  'about:',
] as const);

export type IabNavigationDecision = Readonly<{
  allowed: boolean;
  reasonCode:
    | 'allowed'
    | 'url_invalid'
    | 'protocol_not_allowed'
    | 'about_url_not_allowed';
}>;

function decision(
  allowed: boolean,
  reasonCode: IabNavigationDecision['reasonCode'],
): IabNavigationDecision {
  return Object.freeze({ allowed, reasonCode });
}

/**
 * Top-level navigation gate for an iab view. Only http/https documents and
 * `about:blank` may load; everything else (file:, javascript:, data:, chrome:,
 * custom schemes, ...) is denied. Credentials embedded in the URL are denied
 * as well — the shared `persist:memstack-iab` session is the credential
 * boundary, not the URL bar.
 */
export function evaluateIabNavigation(target: unknown): IabNavigationDecision {
  if (typeof target !== 'string' || target.length === 0 || target.length > 8192) {
    return decision(false, 'url_invalid');
  }
  let url: URL;
  try {
    url = new URL(target);
  } catch {
    return decision(false, 'url_invalid');
  }
  if (url.protocol === 'about:') {
    return url.pathname === 'blank'
      ? decision(true, 'allowed')
      : decision(false, 'about_url_not_allowed');
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    return decision(false, 'protocol_not_allowed');
  }
  if (url.username || url.password) {
    return decision(false, 'url_invalid');
  }
  return decision(true, 'allowed');
}

export type IabWindowOpenAction = Readonly<{
  action: 'deny' | 'new-tab';
  url: string | null;
}>;

/**
 * `window.open` never spawns a native window from an iab view. Navigable
 * targets are routed into a new iab tab (`new-tab`), everything else is
 * denied outright.
 */
export function evaluateIabWindowOpen(target: unknown): IabWindowOpenAction {
  const navigation = evaluateIabNavigation(target);
  if (navigation.allowed && typeof target === 'string') {
    return Object.freeze({ action: 'new-tab', url: target });
  }
  return Object.freeze({ action: 'deny', url: null });
}

/**
 * iab views receive no permission grants by default: no camera, microphone,
 * geolocation, notifications, clipboard read, or anything else. Both the
 * check and the request handler consult this single decision.
 */
export function isIabPermissionAllowed(): boolean {
  return false;
}
