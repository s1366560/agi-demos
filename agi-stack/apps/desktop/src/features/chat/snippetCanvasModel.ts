import type {
  LiveArtifactCanvasState,
  LiveArtifactCanvasTab,
} from './artifactCanvasEventModel';

/**
 * "Open in canvas" for chat code blocks. A code block publishes a snippet
 * request; the App-level subscriber folds it into the live artifact canvas
 * state as a local scratch tab. Scratch tabs deliberately carry no backend
 * artifact identity — the id is a client-only `local-snippet-*` value, the
 * tab is flagged `local: true`, and the canvas surface renders it with a
 * local-scratch badge while keeping save/load/download through the artifact
 * client disabled.
 */

export type SnippetCanvasRequest = {
  code: string;
  language: string;
  title?: string;
};

export type SnippetCanvasOpenResult = {
  tabId: string | null;
  state: LiveArtifactCanvasState;
};

export const LOCAL_SNIPPET_TAB_ID_PREFIX = 'local-snippet-';

export function snippetCanvasTabId(sequence: number): string {
  return `${LOCAL_SNIPPET_TAB_ID_PREFIX}${Math.max(1, Math.floor(sequence))}`;
}

export function isLocalSnippetCanvasTab(
  tab: Pick<LiveArtifactCanvasTab, 'id' | 'local'>,
): boolean {
  return tab.local === true || tab.id.startsWith(LOCAL_SNIPPET_TAB_ID_PREFIX);
}

/**
 * Fold a snippet request into the canvas state as the active tab. Empty or
 * whitespace-only snippets are rejected without touching the state. Reopening
 * the same sequence id replaces the tab instead of duplicating it.
 */
export function openSnippetCanvasTab(
  state: LiveArtifactCanvasState,
  request: SnippetCanvasRequest,
  sequence: number,
): SnippetCanvasOpenResult {
  if (!request.code.trim()) return { tabId: null, state };
  const tabId = snippetCanvasTabId(sequence);
  const language = request.language.trim() || 'plaintext';
  const tab: LiveArtifactCanvasTab = {
    id: tabId,
    title: request.title?.trim() || `${language} snippet`,
    content: request.code,
    contentType: 'code',
    language,
    local: true,
  };
  const openRevision = state.openRevision + 1;
  return {
    tabId,
    state: {
      tabs: [...state.tabs.filter((candidate) => candidate.id !== tabId), tab],
      activeArtifactId: tabId,
      openRevision,
      openGenerations: {
        ...(state.openGenerations ?? {}),
        [tabId]: openRevision,
      },
    },
  };
}

/**
 * Module-level request channel between code blocks (publishers) and the App
 * canvas mount (subscriber). Code blocks render deep inside ChatPanel, which
 * cannot receive new props without churn across forbidden files, so the
 * request travels over this narrow channel instead — mirroring the
 * agent-socket-connected module subscription pattern. `publish` returns
 * whether a live subscriber received the request, so the publisher can show
 * honest feedback when no canvas mount is listening.
 */
type SnippetCanvasRequestListener = (request: SnippetCanvasRequest) => void;

const snippetCanvasRequestListeners = new Set<SnippetCanvasRequestListener>();

export function subscribeSnippetCanvasRequests(
  listener: SnippetCanvasRequestListener,
): () => void {
  snippetCanvasRequestListeners.add(listener);
  return () => {
    snippetCanvasRequestListeners.delete(listener);
  };
}

export function publishSnippetCanvasRequest(request: SnippetCanvasRequest): boolean {
  if (!request.code.trim() || snippetCanvasRequestListeners.size === 0) return false;
  for (const listener of snippetCanvasRequestListeners) listener(request);
  return true;
}
