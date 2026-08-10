/**
 * Minimal preload for in-app browser (iab) WebContentsViews.
 *
 * It deliberately exposes nothing: agent-driven tabs must not gain any
 * desktop capability beyond what a plain web page has. The agent cursor
 * `chrome.runtime` shim is injected into the page's main world via
 * `webContents.executeJavaScript` (see `electron/main/iab/iabCursor.ts`), not
 * through this preload, so untrusted page script never shares a context with
 * privileged bridge code.
 */

export {};
