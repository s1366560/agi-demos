import {
  SIDE_PANEL_SOURCE,
  type ConversationSummary,
  type PanelSocketEvent,
  type PanelTimelineEntry,
} from '../../src/sidepanel-chat';

/**
 * Side panel chat (page half). Dumb UI: every privileged call is proxied to
 * the service worker over chrome.runtime messages; the SW owns all HTTP/WS
 * traffic and pushes live timeline events back the same way.
 */

const pickerEl = document.getElementById('conversation-picker') as HTMLSelectElement;
const newButtonEl = document.getElementById('new-conversation') as HTMLButtonElement;
const statusEl = document.getElementById('status') as HTMLDivElement;
const timelineEl = document.getElementById('timeline') as HTMLDivElement;
const composerEl = document.getElementById('composer') as HTMLFormElement;
const inputEl = document.getElementById('composer-input') as HTMLTextAreaElement;
const sendEl = document.getElementById('composer-send') as HTMLButtonElement;

interface PanelResponse {
  ok: boolean;
  result?: unknown;
  error?: string;
}

let conversations: ConversationSummary[] = [];
let activeConversationId: string | null = null;
const renderedItemIds = new Set<string>();

async function call<T>(method: string, params?: unknown): Promise<T> {
  const response = (await chrome.runtime.sendMessage({
    source: SIDE_PANEL_SOURCE,
    method,
    params,
  })) as PanelResponse | undefined;
  if (!response) throw new Error('no response from the MemStack service worker');
  if (!response.ok) throw new Error(response.error ?? `${method} failed`);
  return response.result as T;
}

function setStatus(text: string | null, tone: 'info' | 'error' = 'info'): void {
  if (text === null) {
    statusEl.hidden = true;
    statusEl.textContent = '';
    return;
  }
  statusEl.hidden = false;
  statusEl.textContent = text;
  statusEl.classList.toggle('status-error', tone === 'error');
}

function renderPicker(): void {
  pickerEl.replaceChildren();
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent =
    conversations.length === 0 ? 'No conversations yet' : 'Pick a conversation…';
  pickerEl.append(placeholder);
  for (const conversation of conversations) {
    const option = document.createElement('option');
    option.value = conversation.id;
    option.textContent = conversation.title;
    pickerEl.append(option);
  }
  pickerEl.value = activeConversationId ?? '';
}

function scrollToBottom(): void {
  timelineEl.scrollTop = timelineEl.scrollHeight;
}

function appendEntry(entry: PanelTimelineEntry): void {
  if (renderedItemIds.has(entry.id)) return;
  renderedItemIds.add(entry.id);
  if (entry.kind === 'desktop-required') {
    const note = document.createElement('div');
    note.className = 'entry entry-handoff';
    const summary = document.createElement('div');
    summary.className = 'handoff-summary';
    summary.textContent = entry.summary;
    const hint = document.createElement('div');
    hint.className = 'handoff-hint';
    hint.textContent = 'Continue in the desktop app';
    note.append(summary, hint);
    timelineEl.append(note);
  } else {
    const bubble = document.createElement('div');
    bubble.className = `entry entry-text entry-${entry.role === 'user' ? 'user' : 'assistant'}`;
    bubble.textContent = entry.text;
    timelineEl.append(bubble);
  }
  scrollToBottom();
}

async function refreshConversations(): Promise<void> {
  const { conversations: list } = await call<{ conversations: ConversationSummary[] }>(
    'sidepanel.listConversations',
  );
  conversations = list;
  renderPicker();
}

async function openConversation(conversationId: string): Promise<void> {
  activeConversationId = conversationId;
  renderedItemIds.clear();
  timelineEl.replaceChildren();
  sendEl.disabled = false;
  renderPicker();
  setStatus(null);
  try {
    const { items } = await call<{ items: PanelTimelineEntry[] }>('sidepanel.getHistory', {
      conversationId,
    });
    for (const item of items) appendEntry(item);
    await call('sidepanel.subscribe', { conversationId });
  } catch (error) {
    setStatus(error instanceof Error ? error.message : String(error), 'error');
  }
}

pickerEl.addEventListener('change', () => {
  if (pickerEl.value) void openConversation(pickerEl.value);
});

newButtonEl.addEventListener('click', async () => {
  newButtonEl.disabled = true;
  try {
    const { conversation } = await call<{ conversation: ConversationSummary }>(
      'sidepanel.createConversation',
      { title: 'Side panel chat' },
    );
    conversations = [conversation, ...conversations];
    await openConversation(conversation.id);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : String(error), 'error');
  } finally {
    newButtonEl.disabled = false;
  }
});

composerEl.addEventListener('submit', (event) => {
  event.preventDefault();
  if (!activeConversationId) return;
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = '';
  const optimisticId = `local-${Date.now()}`;
  appendEntry({ kind: 'text', id: optimisticId, role: 'user', text, timestamp: null });
  void call('sidepanel.sendMessage', { conversationId: activeConversationId, message: text }).catch(
    (error: unknown) => {
      setStatus(error instanceof Error ? error.message : String(error), 'error');
    },
  );
});

chrome.runtime.onMessage.addListener((message) => {
  if (typeof message !== 'object' || message === null) return;
  const event = message as PanelSocketEvent;
  if (event.source !== SIDE_PANEL_SOURCE) return;
  if (event.type === 'status') {
    setStatus(event.connected ? null : 'Reconnecting to the desktop app…');
    return;
  }
  if (event.type === 'timeline' && event.item && event.conversationId === activeConversationId) {
    appendEntry(event.item);
  }
});

void refreshConversations().catch((error: unknown) => {
  setStatus(
    error instanceof Error ? error.message : 'Could not reach the MemStack desktop app',
    'error',
  );
});
