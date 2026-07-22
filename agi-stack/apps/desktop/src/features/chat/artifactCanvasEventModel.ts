export type LiveArtifactCanvasTab = {
  id: string;
  title: string;
  content: string;
  contentType: string;
  language: string | null;
};

export type LiveArtifactCanvasState = {
  tabs: LiveArtifactCanvasTab[];
  activeArtifactId: string | null;
  openRevision: number;
};

export type ArtifactCanvasStreamEventResult = {
  handled: boolean;
  action: 'open' | 'update' | 'close' | null;
  state: LiveArtifactCanvasState;
};

type ArtifactCanvasEvent = {
  type: 'artifact_open' | 'artifact_update' | 'artifact_close';
  data: Record<string, unknown>;
};

export function emptyArtifactCanvasState(): LiveArtifactCanvasState {
  return { tabs: [], activeArtifactId: null, openRevision: 0 };
}

export function applyArtifactCanvasStreamEvent(
  state: LiveArtifactCanvasState,
  event: unknown,
): ArtifactCanvasStreamEventResult {
  const parsed = readArtifactCanvasEvent(event);
  if (!parsed) return { handled: false, action: null, state };
  const artifactId = stringField(parsed.data, 'artifact_id', 'artifactId');

  if (parsed.type === 'artifact_open') {
    const content = stringField(parsed.data, 'content');
    if (!artifactId || !content) return { handled: true, action: null, state };
    const tab: LiveArtifactCanvasTab = {
      id: artifactId,
      title: stringField(parsed.data, 'title') ?? '',
      content,
      contentType: stringField(parsed.data, 'content_type', 'contentType') ?? 'code',
      language: stringField(parsed.data, 'language'),
    };
    const existingIndex = state.tabs.findIndex((candidate) => candidate.id === artifactId);
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
        openRevision: state.openRevision + 1,
      },
    };
  }

  if (parsed.type === 'artifact_update') {
    const content = stringField(parsed.data, 'content');
    if (!artifactId || content === null) return { handled: true, action: null, state };
    const target = state.tabs.find((candidate) => candidate.id === artifactId);
    if (!target) return { handled: true, action: 'update', state };
    const nextContent = parsed.data.append === true ? `${target.content}${content}` : content;
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
    },
  };
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
    for (const key of ['data', 'payload']) {
      const nested = recordValue(current[key]);
      if (nested) queue.push(nested);
    }
  }
  return null;
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
