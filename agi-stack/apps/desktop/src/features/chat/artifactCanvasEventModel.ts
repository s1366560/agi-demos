export type LiveArtifactCanvasTab = {
  id: string;
  title: string;
  content: string;
  contentType: string;
  language: string | null;
  mimeType?: string;
  sizeBytes?: number;
};

export type LiveArtifactCanvasState = {
  tabs: LiveArtifactCanvasTab[];
  activeArtifactId: string | null;
  openRevision: number;
  openGenerations: Record<string, number>;
};

export type ArtifactCanvasStreamEventResult = {
  handled: boolean;
  action: 'open' | 'update' | 'close' | null;
  state: LiveArtifactCanvasState;
};

type ArtifactCanvasEvent = {
  type:
    | 'artifact_open'
    | 'artifact_update'
    | 'artifact_close'
    | 'a2ui_canvas_open'
    | 'a2ui_canvas_update'
    | 'a2ui_canvas_close';
  data: Record<string, unknown>;
};

export function emptyArtifactCanvasState(): LiveArtifactCanvasState {
  return {
    tabs: [],
    activeArtifactId: null,
    openRevision: 0,
    openGenerations: {},
  };
}

export function applyArtifactCanvasStreamEvent(
  state: LiveArtifactCanvasState,
  event: unknown,
): ArtifactCanvasStreamEventResult {
  const parsed = readArtifactCanvasEvent(event);
  if (!parsed) return { handled: false, action: null, state };
  const artifactId = stringField(parsed.data, 'artifact_id', 'artifactId');

  if (parsed.type === 'artifact_open' || parsed.type === 'a2ui_canvas_open') {
    const content = stringField(parsed.data, 'content');
    if (!artifactId || !content) return { handled: true, action: null, state };
    const mimeType = stringField(parsed.data, 'mime_type', 'mimeType');
    const sizeBytes = numberField(parsed.data, 'size_bytes', 'sizeBytes');
    const tab: LiveArtifactCanvasTab = {
      id: artifactId,
      title: stringField(parsed.data, 'title') ?? '',
      content,
      contentType: stringField(parsed.data, 'content_type', 'contentType') ?? 'code',
      language: stringField(parsed.data, 'language'),
      ...(mimeType ? { mimeType } : {}),
      ...(sizeBytes !== null ? { sizeBytes } : {}),
    };
    const existingIndex = state.tabs.findIndex((candidate) => candidate.id === artifactId);
    const openRevision = state.openRevision + 1;
    const tabs =
      existingIndex < 0
        ? [...state.tabs, tab]
        : state.tabs.map((candidate, index) => (index === existingIndex ? tab : candidate));
    return {
      handled: true,
      action: 'open',
      state: {
        tabs,
        activeArtifactId: artifactId,
        openRevision,
        openGenerations: {
          ...(state.openGenerations ?? {}),
          [artifactId]: openRevision,
        },
      },
    };
  }

  if (parsed.type === 'artifact_update' || parsed.type === 'a2ui_canvas_update') {
    const content = stringField(parsed.data, 'content');
    if (!artifactId || content === null) return { handled: true, action: null, state };
    const target = state.tabs.find((candidate) => candidate.id === artifactId);
    if (!target) return { handled: true, action: 'update', state };
    const nextContent =
      parsed.type === 'a2ui_canvas_update'
        ? a2uiCanvasUpdateReplacesSnapshot(content)
          ? content
          : `${target.content}\n${content}`
        : parsed.data.append === true
          ? `${target.content}${content}`
          : content;
    if (nextContent === target.content) return { handled: true, action: 'update', state };
    return {
      handled: true,
      action: 'update',
      state: {
        ...state,
        tabs: state.tabs.map((candidate) =>
          candidate.id === artifactId ? { ...candidate, content: nextContent } : candidate,
        ),
      },
    };
  }

  if (!artifactId) return { handled: true, action: null, state };
  if (
    parsed.type === 'a2ui_canvas_close' &&
    state.tabs.find((candidate) => candidate.id === artifactId)?.contentType !==
      'a2ui_surface'
  ) {
    return { handled: false, action: null, state };
  }
  const tabs = state.tabs.filter((candidate) => candidate.id !== artifactId);
  if (tabs.length === state.tabs.length) return { handled: true, action: 'close', state };
  return {
    handled: true,
    action: 'close',
    state: {
      tabs,
      activeArtifactId:
        state.activeArtifactId === artifactId
          ? (tabs[tabs.length - 1]?.id ?? null)
          : state.activeArtifactId,
      openRevision: state.openRevision,
      openGenerations: Object.fromEntries(
        Object.entries(state.openGenerations ?? {}).filter(([id]) => id !== artifactId),
      ),
    },
  };
}

export function replayArtifactCanvasEvents(events: readonly unknown[]): LiveArtifactCanvasState {
  let state = emptyArtifactCanvasState();
  for (const event of events) {
    state = applyArtifactCanvasStreamEvent(state, event).state;
  }
  return state;
}

export function selectArtifactCanvasTab(
  state: LiveArtifactCanvasState,
  artifactId: string,
): LiveArtifactCanvasState {
  if (
    state.activeArtifactId === artifactId ||
    !state.tabs.some((candidate) => candidate.id === artifactId)
  ) {
    return state;
  }
  return { ...state, activeArtifactId: artifactId };
}

export type ArtifactCanvasViewMode = 'code' | 'markdown' | 'data' | 'preview';

export type ArtifactCanvasWorkspaceTab = LiveArtifactCanvasTab & {
  sourceContent: string;
  sourceSignature: string;
  draftContent: string;
  dirty: boolean;
  pinned: boolean;
  viewMode: ArtifactCanvasViewMode;
  authorityState: 'open' | 'closed';
  undoStack: string[];
  redoStack: string[];
};

export type ArtifactCanvasWorkspaceState = {
  tabs: ArtifactCanvasWorkspaceTab[];
  activeArtifactId: string | null;
  sourceActiveArtifactId: string | null;
  pendingCloseArtifactId: string | null;
  dismissedTabSignatures: Record<string, string>;
};

export type ArtifactCanvasTabCloseResult = {
  status: 'closed' | 'confirmation_required' | 'blocked_pinned' | 'unchanged';
  state: ArtifactCanvasWorkspaceState;
};

export type ArtifactCanvasDownloadDescriptor = {
  filename: string;
  mimeType: string;
  content: string;
};

export const ARTIFACT_CANVAS_VIEW_MODES: readonly ArtifactCanvasViewMode[] = Object.freeze([
  'code',
  'markdown',
  'data',
  'preview',
]);

export const ARTIFACT_CANVAS_SAVE_CAPABILITY = Object.freeze({
  available: true,
  contractVersion: 2 as const,
});

const artifactCanvasViewModeSet = new Set<ArtifactCanvasViewMode>(
  ARTIFACT_CANVAS_VIEW_MODES,
);

export function createArtifactCanvasWorkspace(
  source: LiveArtifactCanvasState,
): ArtifactCanvasWorkspaceState {
  const tabs = source.tabs.map((tab) =>
    createArtifactCanvasWorkspaceTab(tab, artifactCanvasOpenGeneration(source, tab.id)),
  );
  return {
    tabs,
    activeArtifactId: activeArtifactIdForTabs(source.activeArtifactId, tabs),
    sourceActiveArtifactId: source.activeArtifactId,
    pendingCloseArtifactId: null,
    dismissedTabSignatures: {},
  };
}

export function reconcileArtifactCanvasWorkspace(
  workspace: ArtifactCanvasWorkspaceState,
  source: LiveArtifactCanvasState,
): ArtifactCanvasWorkspaceState {
  const existingById = new Map(workspace.tabs.map((tab) => [tab.id, tab]));
  const sourceIds = new Set(source.tabs.map((tab) => tab.id));
  const dismissedTabSignatures = Object.fromEntries(
    Object.entries(workspace.dismissedTabSignatures).filter(([id]) => sourceIds.has(id)),
  );
  const sourceTabs = source.tabs.flatMap((tab) => {
    const openGeneration = artifactCanvasOpenGeneration(source, tab.id);
    const signature = artifactCanvasSourceSignature(tab, openGeneration);
    const existing = existingById.get(tab.id);
    if (!existing) {
      return dismissedTabSignatures[tab.id] === signature
        ? []
        : [createArtifactCanvasWorkspaceTab(tab, openGeneration)];
    }
    if (existing.sourceSignature === signature) {
      return existing.authorityState === 'open'
        ? [existing]
        : [{ ...existing, authorityState: 'open' as const }];
    }
    const draftContent = existing.dirty ? existing.draftContent : tab.content;
    const dirty = draftContent !== tab.content;
    return [
      {
        ...existing,
        title: tab.title,
        content: tab.content,
        contentType: tab.contentType,
        language: tab.language,
        mimeType: tab.mimeType,
        sizeBytes: tab.sizeBytes,
        sourceContent: tab.content,
        sourceSignature: signature,
        draftContent,
        dirty,
        authorityState: 'open' as const,
      },
    ];
  });
  const dirtyOrphans = workspace.tabs
    .filter((tab) => !sourceIds.has(tab.id) && tab.dirty)
    .map((tab) =>
      tab.authorityState === 'closed'
        ? tab
        : { ...tab, authorityState: 'closed' as const },
    );
  const tabs = [...sourceTabs, ...dirtyOrphans];
  const sourceSelectionChanged =
    source.activeArtifactId !== workspace.sourceActiveArtifactId;
  const desiredActiveArtifactId = sourceSelectionChanged
    ? source.activeArtifactId
    : workspace.activeArtifactId;
  const pendingCloseArtifactId = tabs.some(
    (tab) => tab.id === workspace.pendingCloseArtifactId,
  )
    ? workspace.pendingCloseArtifactId
    : null;
  return {
    tabs,
    activeArtifactId: activeArtifactIdForTabs(desiredActiveArtifactId, tabs),
    sourceActiveArtifactId: source.activeArtifactId,
    pendingCloseArtifactId,
    dismissedTabSignatures,
  };
}

export function selectArtifactCanvasWorkspaceTab(
  workspace: ArtifactCanvasWorkspaceState,
  artifactId: string,
): ArtifactCanvasWorkspaceState {
  if (
    workspace.activeArtifactId === artifactId ||
    !workspace.tabs.some((tab) => tab.id === artifactId)
  ) {
    return workspace;
  }
  return { ...workspace, activeArtifactId: artifactId };
}

export function toggleArtifactCanvasTabPin(
  workspace: ArtifactCanvasWorkspaceState,
  artifactId: string,
): ArtifactCanvasWorkspaceState {
  if (!workspace.tabs.some((tab) => tab.id === artifactId)) return workspace;
  return {
    ...workspace,
    tabs: workspace.tabs.map((tab) =>
      tab.id === artifactId ? { ...tab, pinned: !tab.pinned } : tab,
    ),
  };
}

export function setArtifactCanvasViewMode(
  workspace: ArtifactCanvasWorkspaceState,
  artifactId: string,
  viewMode: ArtifactCanvasViewMode,
): ArtifactCanvasWorkspaceState {
  if (!artifactCanvasViewModeSet.has(viewMode)) return workspace;
  const target = workspace.tabs.find((tab) => tab.id === artifactId);
  if (!target || target.viewMode === viewMode) return workspace;
  return {
    ...workspace,
    tabs: workspace.tabs.map((tab) =>
      tab.id === artifactId ? { ...tab, viewMode } : tab,
    ),
  };
}

export function editArtifactCanvasWorkspaceContent(
  workspace: ArtifactCanvasWorkspaceState,
  artifactId: string,
  content: string,
): ArtifactCanvasWorkspaceState {
  const target = workspace.tabs.find((tab) => tab.id === artifactId);
  if (!target || target.draftContent === content) return workspace;
  return {
    ...workspace,
    tabs: workspace.tabs.map((tab) =>
      tab.id === artifactId
        ? {
            ...tab,
            draftContent: content,
            dirty: content !== tab.sourceContent,
            undoStack: [...tab.undoStack, tab.draftContent].slice(-100),
            redoStack: [],
          }
        : tab,
    ),
  };
}

export function undoArtifactCanvasWorkspaceContent(
  workspace: ArtifactCanvasWorkspaceState,
  artifactId: string,
): ArtifactCanvasWorkspaceState {
  const target = workspace.tabs.find((tab) => tab.id === artifactId);
  const previous = target?.undoStack.at(-1);
  if (!target || previous === undefined) return workspace;
  return {
    ...workspace,
    tabs: workspace.tabs.map((tab) =>
      tab.id === artifactId
        ? {
            ...tab,
            draftContent: previous,
            dirty: previous !== tab.sourceContent,
            undoStack: tab.undoStack.slice(0, -1),
            redoStack: [...tab.redoStack, tab.draftContent].slice(-100),
          }
        : tab,
    ),
  };
}

export function redoArtifactCanvasWorkspaceContent(
  workspace: ArtifactCanvasWorkspaceState,
  artifactId: string,
): ArtifactCanvasWorkspaceState {
  const target = workspace.tabs.find((tab) => tab.id === artifactId);
  const next = target?.redoStack.at(-1);
  if (!target || next === undefined) return workspace;
  return {
    ...workspace,
    tabs: workspace.tabs.map((tab) =>
      tab.id === artifactId
        ? {
            ...tab,
            draftContent: next,
            dirty: next !== tab.sourceContent,
            undoStack: [...tab.undoStack, tab.draftContent].slice(-100),
            redoStack: tab.redoStack.slice(0, -1),
          }
        : tab,
    ),
  };
}

export function markArtifactCanvasWorkspaceSaved(
  workspace: ArtifactCanvasWorkspaceState,
  artifactId: string,
): ArtifactCanvasWorkspaceState {
  const target = workspace.tabs.find((tab) => tab.id === artifactId);
  if (!target || !target.dirty) return workspace;
  return {
    ...workspace,
    tabs: workspace.tabs.map((tab) =>
      tab.id === artifactId
        ? {
            ...tab,
            content: tab.draftContent,
            sourceContent: tab.draftContent,
            dirty: false,
            redoStack: [],
          }
        : tab,
    ),
  };
}

export function applyArtifactCanvasWorkspaceAuthorityContent(
  workspace: ArtifactCanvasWorkspaceState,
  artifactId: string,
  content: string,
  mimeType: string,
  preserveDirtyDraft = true,
): ArtifactCanvasWorkspaceState {
  const target = workspace.tabs.find((tab) => tab.id === artifactId);
  if (!target) return workspace;
  const preserveDraft = preserveDirtyDraft && target.dirty;
  return {
    ...workspace,
    tabs: workspace.tabs.map((tab) =>
      tab.id === artifactId
        ? {
            ...tab,
            content,
            sourceContent: content,
            draftContent: preserveDraft ? tab.draftContent : content,
            dirty: preserveDraft ? tab.draftContent !== content : false,
            mimeType,
            redoStack: [],
          }
        : tab,
    ),
  };
}

export function requestArtifactCanvasTabClose(
  workspace: ArtifactCanvasWorkspaceState,
  artifactId: string,
): ArtifactCanvasTabCloseResult {
  const target = workspace.tabs.find((tab) => tab.id === artifactId);
  if (!target) return { status: 'unchanged', state: workspace };
  if (target.pinned) return { status: 'blocked_pinned', state: workspace };
  if (target.dirty) {
    return {
      status: 'confirmation_required',
      state: { ...workspace, pendingCloseArtifactId: artifactId },
    };
  }
  return {
    status: 'closed',
    state: dismissArtifactCanvasWorkspaceTab(workspace, artifactId),
  };
}

export function confirmArtifactCanvasTabClose(
  workspace: ArtifactCanvasWorkspaceState,
): ArtifactCanvasWorkspaceState {
  if (!workspace.pendingCloseArtifactId) return workspace;
  return dismissArtifactCanvasWorkspaceTab(
    workspace,
    workspace.pendingCloseArtifactId,
  );
}

export function cancelArtifactCanvasTabClose(
  workspace: ArtifactCanvasWorkspaceState,
): ArtifactCanvasWorkspaceState {
  return workspace.pendingCloseArtifactId
    ? { ...workspace, pendingCloseArtifactId: null }
    : workspace;
}

export function formatArtifactCanvasData(content: string): string {
  try {
    const value: unknown = JSON.parse(content);
    return JSON.stringify(value, null, 2);
  } catch {
    return content;
  }
}

export function artifactCanvasDownloadDescriptor(
  tab: ArtifactCanvasWorkspaceTab,
): ArtifactCanvasDownloadDescriptor {
  return {
    filename: artifactCanvasDownloadFilename(tab.title),
    mimeType:
      tab.mimeType ??
      (tab.contentType === 'markdown'
        ? 'text/markdown;charset=utf-8'
        : tab.contentType === 'data'
          ? 'application/json'
          : 'text/plain;charset=utf-8'),
    content: tab.draftContent,
  };
}

function createArtifactCanvasWorkspaceTab(
  tab: LiveArtifactCanvasTab,
  openGeneration: number,
): ArtifactCanvasWorkspaceTab {
  return {
    ...tab,
    sourceContent: tab.content,
    sourceSignature: artifactCanvasSourceSignature(tab, openGeneration),
    draftContent: tab.content,
    dirty: false,
    pinned: false,
    viewMode: defaultArtifactCanvasViewMode(tab.contentType),
    authorityState: 'open',
    undoStack: [],
    redoStack: [],
  };
}

function dismissArtifactCanvasWorkspaceTab(
  workspace: ArtifactCanvasWorkspaceState,
  artifactId: string,
): ArtifactCanvasWorkspaceState {
  const targetIndex = workspace.tabs.findIndex((tab) => tab.id === artifactId);
  if (targetIndex < 0) {
    return workspace.pendingCloseArtifactId
      ? { ...workspace, pendingCloseArtifactId: null }
      : workspace;
  }
  const target = workspace.tabs[targetIndex];
  const tabs = workspace.tabs.filter((tab) => tab.id !== artifactId);
  const fallbackIndex = Math.min(targetIndex, tabs.length - 1);
  return {
    ...workspace,
    tabs,
    activeArtifactId:
      workspace.activeArtifactId === artifactId
        ? (tabs[fallbackIndex]?.id ?? null)
        : workspace.activeArtifactId,
    pendingCloseArtifactId: null,
    dismissedTabSignatures: {
      ...workspace.dismissedTabSignatures,
      [artifactId]: target.sourceSignature,
    },
  };
}

function activeArtifactIdForTabs(
  desiredArtifactId: string | null,
  tabs: readonly ArtifactCanvasWorkspaceTab[],
): string | null {
  return tabs.some((tab) => tab.id === desiredArtifactId)
    ? desiredArtifactId
    : (tabs[tabs.length - 1]?.id ?? null);
}

function defaultArtifactCanvasViewMode(contentType: string): ArtifactCanvasViewMode {
  return contentType === 'markdown' ||
    contentType === 'data' ||
    contentType === 'preview' ||
    contentType === 'a2ui_surface'
    ? contentType === 'a2ui_surface'
      ? 'preview'
      : contentType
    : 'code';
}

function artifactCanvasOpenGeneration(
  source: LiveArtifactCanvasState,
  artifactId: string,
): number {
  return source.openGenerations?.[artifactId] ?? source.openRevision;
}

function artifactCanvasSourceSignature(
  tab: LiveArtifactCanvasTab,
  openGeneration: number,
): string {
  return JSON.stringify([
    openGeneration,
    tab.id,
    tab.title,
    tab.content,
    tab.contentType,
    tab.language,
    tab.mimeType ?? null,
    tab.sizeBytes ?? null,
  ]);
}

function artifactCanvasDownloadFilename(title: string): string {
  const leaf = title.split(/[\\/]/).filter(Boolean).at(-1) ?? '';
  const sanitized = leaf.replace(/[\u0000-\u001f<>:"/\\|?*]/g, '_').trim();
  return sanitized || 'artifact.txt';
}

function readArtifactCanvasEvent(event: unknown): ArtifactCanvasEvent | null {
  const root = recordValue(event);
  if (!root) return null;
  const queue = [root];
  const seen = new Set<Record<string, unknown>>();
  while (queue.length) {
    const current = queue.shift();
    if (!current || seen.has(current)) continue;
    seen.add(current);
    const type = stringField(current, 'type', 'event_type');
    if (type === 'artifact_open' || type === 'artifact_update' || type === 'artifact_close') {
      return {
        type,
        data: recordValue(current.data) ?? recordValue(current.payload) ?? current,
      };
    }
    if (type === 'canvas_updated') {
      const data = recordValue(current.data) ?? recordValue(current.payload) ?? current;
      const action = stringField(data, 'action');
      const artifactId = stringField(data, 'block_id', 'blockId');
      const block = recordValue(data.block);
      const blockType = block ? stringField(block, 'block_type', 'blockType') : null;
      if (!artifactId || !action) return { type: 'a2ui_canvas_update', data: {} };
      if (action === 'deleted') {
        return {
          type: 'a2ui_canvas_close',
          data: { artifact_id: artifactId },
        };
      }
      if (blockType !== 'a2ui_surface') return null;
      const content = block ? stringField(block, 'content') : null;
      const title = block ? stringField(block, 'title') : null;
      const normalizedData: Record<string, unknown> = {
        artifact_id: artifactId,
        content_type: 'a2ui_surface',
        ...(title ? { title } : {}),
        ...(content ? { content } : {}),
      };
      if (action === 'created') {
        return { type: 'a2ui_canvas_open', data: normalizedData };
      }
      if (action === 'updated') {
        return { type: 'a2ui_canvas_update', data: normalizedData };
      }
      return { type: 'a2ui_canvas_update', data: {} };
    }
    for (const key of ['data', 'payload']) {
      const nested = recordValue(current[key]);
      if (nested) queue.push(nested);
    }
  }
  return null;
}

function a2uiCanvasUpdateReplacesSnapshot(content: string): boolean {
  for (const line of content.split(/\r?\n/u)) {
    if (!line.trim()) continue;
    try {
      const record = recordValue(JSON.parse(line));
      if (recordValue(record?.beginRendering) || recordValue(record?.deleteSurface)) return true;
    } catch {
      return true;
    }
  }
  return false;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringField(record: Record<string, unknown>, ...keys: string[]): string | null {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string') return value;
  }
  return null;
}

function numberField(record: Record<string, unknown>, ...keys: string[]): number | null {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'number' && Number.isSafeInteger(value) && value >= 0) {
      return value;
    }
  }
  return null;
}
