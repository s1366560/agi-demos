import type { SlotBridgeIdentityV2 } from '@agistack/plugin-slots';

const MODULES = new Set([
  'builtin:web-slot-navigation',
  'builtin:web-slot-settings',
  'builtin:web-slot-conversation',
  'builtin:web-slot-composer',
  'builtin:web-slot-canvas',
  'builtin:web-slot-tool-result',
]);

/** Resources are shipped with this application; no module URL, network or runtime code import. */
export function createPluginSlotDocumentV2(
  moduleRef: string,
  identity: SlotBridgeIdentityV2
): string | null {
  if (!MODULES.has(moduleRef)) return null;
  const nonce = identity.instanceNonce;
  const encoded = JSON.stringify(identity).replace(/</g, '\\u003c');
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-${nonce}'; style-src 'nonce-${nonce}'; connect-src 'none'; img-src 'none'; form-action 'none'; base-uri 'none'"><style nonce="${nonce}">body{margin:0;font:13px system-ui;color:#64748b}nav{display:flex;flex-wrap:wrap;gap:6px}button{font:inherit;color:inherit;padding:4px 8px;border:1px solid #cbd5e1;border-radius:6px;background:transparent;cursor:pointer}button:disabled{opacity:.45;cursor:default}pre{white-space:pre-wrap;margin:0}</style></head><body><main id="root"></main><script nonce="${nonce}">
(() => {
  const identity = ${encoded};
  let port;
  let disposed = false;
  const root = document.getElementById('root');
  const same = m => m && m.source === 'memstack-plugin-slot-v2' && m.slotId === identity.slotId && m.instanceNonce === identity.instanceNonce && m.generationId === identity.generationId;
  const send = payload => { if (port && !disposed) port.postMessage({ source: 'memstack-plugin-slot-v2', ...identity, ...payload }); };
  const button = (label, action, disabled = false) => {
    const node = document.createElement('button'); node.type = 'button'; node.textContent = label;
    node.disabled = disabled; node.onclick = () => send({ type: 'slot:action', action }); root.append(node);
  };
  const render = context => {
    root.replaceChildren();
    if (!context || typeof context !== 'object') return;
    switch (context.kind) {
      case 'navigation': context.destinations.forEach(item => button(item.label, { type: 'navigate', destinationId: item.id })); break;
      case 'settings': context.sections.forEach(item => button(item.label, { type: 'settings.open', sectionId: item.id })); break;
      case 'conversation': button(context.commandsLabel, { type: 'conversation.open-commands' }); break;
      case 'composer': button(context.templatesLabel, { type: 'composer.open-templates' }, context.locked); break;
      case 'canvas': context.tabs.forEach(item => button(item.label, { type: 'canvas.select-tab', tabId: item.id }, context.activeTabId === item.id)); break;
      case 'tool-result': {
        const presentation = context.presentation;
        const node = document.createElement('pre');
        if (presentation.kind === 'text') node.textContent = presentation.text;
        else if (presentation.kind === 'summary') node.textContent = presentation.summary;
        else if (presentation.kind === 'diff') node.textContent = presentation.before + '\\n' + presentation.after;
        else if (presentation.kind === 'table') node.textContent = [presentation.columns, ...presentation.rows].map(row => row.join(' | ')).join('\\n');
        root.append(node); break;
      }
    }
    send({ type: 'slot:resize', height: Math.max(1, document.documentElement.scrollHeight) });
  };
  window.addEventListener('message', event => {
    if (disposed || port || event.source !== parent || !same(event.data) || event.data.type !== 'slot:connect' || event.ports.length !== 1) return;
    port = event.ports[0];
    port.onmessage = event => {
      if (!same(event.data) || disposed) return;
      try {
        if (event.data.type === 'slot:init') render(event.data.payload);
        else if (event.data.type === 'slot:dispose') { disposed = true; root.replaceChildren(); port.close(); }
      } catch { send({ type: 'slot:error', message: 'slot_render_failed' }); }
    };
    port.start(); send({ type: 'slot:ready' });
  });
})();
</script></body></html>`;
}
