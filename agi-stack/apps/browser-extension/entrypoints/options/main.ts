import { STATUS_STORAGE_KEY, type NativeStatus } from '../../src/transport';

const extensionIdEl = document.getElementById('extension-id')!;
const stateEl = document.getElementById('connection-state')!;
const lastConnectedAtEl = document.getElementById('last-connected-at')!;
const lastErrorEl = document.getElementById('last-error')!;

function render(status: NativeStatus | undefined): void {
  const connected = status?.connected === true;
  stateEl.textContent = connected ? 'connected' : 'disconnected';
  stateEl.classList.toggle('pill-ok', connected);
  stateEl.classList.toggle('pill-bad', !connected);
  lastConnectedAtEl.textContent = status?.lastConnectedAt
    ? new Date(status.lastConnectedAt).toLocaleString()
    : '—';
  lastErrorEl.textContent = status?.lastError ?? '—';
}

extensionIdEl.textContent = chrome.runtime.id;

void chrome.storage.local.get(STATUS_STORAGE_KEY).then((items) => {
  render(items[STATUS_STORAGE_KEY] as NativeStatus | undefined);
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local') return;
  const change = changes[STATUS_STORAGE_KEY];
  if (change) render(change.newValue as NativeStatus | undefined);
});
