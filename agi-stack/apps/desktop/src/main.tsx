import '@radix-ui/themes/styles.css';
import React from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App';
import { I18nProvider } from './i18n';
import './styles.css';

function formatError(error: unknown): string {
  if (error instanceof Error) {
    return `${error.name}: ${error.message}\n${error.stack ?? ''}`.trim();
  }
  return String(error);
}

function showFatalError(error: unknown) {
  const root = document.getElementById('root');
  if (!root) return;

  const panel = document.createElement('div');
  panel.className = 'app-fatal-error';

  const title = document.createElement('strong');
  title.textContent = 'agi-stack Desktop failed to start';

  const detail = document.createElement('pre');
  detail.textContent = formatError(error);

  panel.append(title, detail);
  root.replaceChildren(panel);
}

function runsInTauriShell(): boolean {
  return Boolean(window.__TAURI__?.core?.invoke || window.__TAURI_INTERNALS__);
}

function markRuntimeShell() {
  const isTauri = runsInTauriShell();
  document.documentElement.dataset.runtimeShell = isTauri ? 'tauri' : 'browser';
  document.documentElement.toggleAttribute('data-tauri-window', isTauri);
}

function reportFrontendReady() {
  if (!import.meta.env.DEV) return;

  const invoke = window.__TAURI__?.core?.invoke;
  if (!invoke) return;

  window.requestAnimationFrame(() => {
    const summary = document.body.innerText.replace(/\s+/g, ' ').trim().slice(0, 240);
    void invoke('frontend_ready', {
      summary: summary || 'mounted without visible text',
    });
  });
}

window.addEventListener('error', (event) => {
  showFatalError(event.error ?? event.message);
});

window.addEventListener('unhandledrejection', (event) => {
  showFatalError(event.reason);
});

try {
  const root = document.getElementById('root');
  if (!root) {
    throw new Error('Missing #root container');
  }

  markRuntimeShell();
  createRoot(root).render(
    <React.StrictMode>
      <I18nProvider>
        <App />
      </I18nProvider>
    </React.StrictMode>,
  );
  reportFrontendReady();
} catch (error) {
  showFatalError(error);
}
