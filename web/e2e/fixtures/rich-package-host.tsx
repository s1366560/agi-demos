import { agentChatRuntime } from './agentChatRuntime';
import { createRoot } from 'react-dom/client';
import { RichPackagePages } from '../../../agi-stack/packages/plugin-marketplace-ui/src/RichPackagePages';
import type { MarketplaceTransport } from '../../../agi-stack/packages/plugin-marketplace-ui/src/client';

const route = '/qa-page';
let digest = 'sha256:' + 'a'.repeat(64);
let corrupt = location.search === '?bad';
const anchor = location.search === '?anchor';
const child = { id: 'pane', title: 'Signed pane', contributes_to: 'qa/tools@1', routes: [], targets: ['web'], query_params: ['selection'] };
let installed = true;
if (anchor) {
  const install = document.createElement('button');
  install.textContent = 'Toggle pane installation';
  install.onclick = () => { installed = !installed; window.dispatchEvent(new Event('focus')); };
  document.body.append(install);
}
const chat = location.search.startsWith('?chat');
const target = chat && !location.search.startsWith('?chat-web') ? 'desktop-renderer' : 'web';
// Electron loads its renderer and trusted frame as siblings in the application root.
if (target === 'desktop-renderer') history.replaceState(null, '', '/index.html' + location.search);
const descriptor = { id: 'test', title: 'QA', routes: [route], targets: [target] };
const log = document.createElement('output');
log.id = 'host-log';
document.body.append(log);
const chatRuntime = agentChatRuntime(
  log,
  location.search === '?chat-denied'
    ? 'device_local_workspace_required'
    : location.search === '?chat-revoked'
      ? 'device_plugin_grant_revoked'
      : undefined
);
if (['?upgrade', '?drain'].includes(location.search)) {
  const upgrade = document.createElement('button');
  upgrade.textContent = 'Install next version';
  upgrade.onclick = () => {
    corrupt = location.search === '?upgrade';
    digest = 'sha256:' + 'b'.repeat(64);
    window.dispatchEvent(new Event('focus'));
  };
  document.body.append(upgrade);
}
const billing = location.search === '?billing';
const sandbox = location.search.startsWith('?sandbox');
let terminalConnected = false;
const source = anchor ? `
  const input = document.createElement('input'); input.placeholder = 'Draft'; document.body.append(input);
  const slot = document.createElement('div'); slot.style.cssText = 'margin:20px;width:280px;height:140px'; document.body.append(slot);
  const handle = document.createElement('button'); handle.textContent = 'Drag divider';
  handle.onpointerdown = event => handle.setPointerCapture(event.pointerId);
  document.body.append(handle);
  const close = window.memstack.anchorSlot('tools@1', slot, '?selection=first&ignored=1');
  const toggle = document.createElement('button'); toggle.textContent = 'Close pane'; toggle.onclick = close; document.body.append(toggle);
  const resize = document.createElement('button'); resize.textContent = 'Resize pane'; resize.onclick = () => slot.style.width='340px'; document.body.append(resize);
` : chat
  ? (await import('../../../plugins/business/agent/ui/chat-web.js?raw')).default
  : sandbox
    ? (await import('../../../plugins/business/environments/ui/interaction.js?raw')).default
    : billing
      ? (await import('../../../plugins/business/billing/ui/web-billing.js?raw')).default
      : `
(async () => {
 const scope = await memstack.scope();
 const request = new AbortController();
 const result = await memstack.invoke('read');
 const denied = await memstack.invoke('write').catch(e => e.message);
 const device = await memstack.device('test').catch(e => e.message);
 const button = document.createElement('button');
 button.textContent = 'Cancel';
 button.onclick = () => request.abort();
 const output = document.createElement('output');
 output.textContent = JSON.stringify({result, denied, device, id:scope.projectId});
 document.getElementById('root').append(button, output);
 await memstack.invoke('wait', {}, {signal:request.signal}).catch(e => {
   const text = document.createElement('p'); text.textContent=e.name; document.body.append(text);
 });
})();
`;
const hash = Array.from(
  new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(source))),
  (n) => n.toString(16).padStart(2, '0')
).join('');
const transport: MarketplaceTransport = async <T,>(
  path: string,
  options: Parameters<MarketplaceTransport>[1]
): Promise<T> => {
  if (path.includes('/?'))
    return {
      items: [
        { plugin_id: 'qa', actual_digest: digest, status: 'enabled', pages: [descriptor] },
        ...(anchor && installed ? [{ plugin_id: 'child', actual_digest: digest, status: 'enabled', pages: [child] }] : []),
        ...(location.search === '?page-links' ? [{
          plugin_id: 'boards',
          actual_digest: digest,
          status: 'enabled',
          pages: [{ ...descriptor, id: 'overview', routes: ['/project/:projectId/board', '/project/:projectId/board/:card'], query_params:['tab'] }],
        }] : []),
      ],
    } as T;
  if (path.includes('/child/ui?')) {
    const guest = `
      memstack.getContext().then(context => {
        document.body.textContent = context.search;
        for (const [label, command] of [['Operate','child-op'], ['Subscribe','wait']]) {
          const button = document.createElement('button');
          button.textContent = label;
          button.onclick = () => memstack.invoke(command);
          document.body.append(button);
        }
      });
    `;
    const bytes = new TextEncoder().encode(guest);
    const sum = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), n => n.toString(16).padStart(2,'0')).join('');
    return { ...child, schema: 'memstack.rich-page/1', release_digest: digest, target, commands:['child-op','wait'], device_tools:[], entry:{path:'widget.js',bytes_base64:btoa(guest),digest:'sha256:'+sum} } as T;
  }
  if (path.includes('/ui?'))
    return {
      ...descriptor,
      schema: 'memstack.rich-page/1',
      query_params: sandbox ? ['run_id', 'revision'] : ['conversationId'],
      ...(anchor ? { anchored_slots: { 'tools@1':'child/pane' } } : {}),
      page_links: ['boards/overview' , 'uninstalled/overview'],
      navigation_routes: [route, '/agent/chat/:conversationId', '/project/:projectId/details/:id'],
      release_digest: digest,
      target,
      commands: chat
        ? ['chat-create', 'chat-list', 'chat-history', 'chat-turn', 'chat-cancel']
        : sandbox
          ? ['sandbox-status', 'project-terminal', 'authorize-run-terminal']
          : billing
            ? ['quote-pro', 'list-invoices']
            : ['read', 'wait'],
      device_tools: chat ? ['local_chat'] : ['test'],
      entry: {
        path: 'qa.js',
        digest: 'sha256:' + (corrupt ? '0'.repeat(64) : hash),
        bytes_base64: btoa(
          Array.from(new TextEncoder().encode(source), (byte) => String.fromCharCode(byte)).join('')
        ),
      },
    } as T;
  const body = options.body as { command_id: string; payload?: unknown };
  if (body.command_id === 'child-op') {
    log.textContent = path + ':' + JSON.stringify(body);
    return {} as T;
  }
  if (chat)
    return chatRuntime.command(body.command_id, body.payload as Record<string, unknown>) as T;
  if (body.command_id === 'sandbox-status') {
    return { sandbox: { sandbox_id: 'dev', status: 'running' } } as T;
  }
  if (body.command_id === 'authorize-run-terminal') {
    log.textContent = JSON.stringify(body.payload);
    if (location.search === '?sandbox-degraded') throw new Error('terminal_authority_unavailable');
    return { channel: 'fixture-channel' } as T;
  }
  if (body.command_id === 'project-terminal') {
    const payload = body.payload as { action: string; channel: string };
    if (payload.channel !== 'fixture-channel' || location.search === '?sandbox-degraded') {
      log.textContent = 'unexpected channel use';
      throw new Error('unknown channel');
    }
    if (payload.action !== 'read') return {} as T;
    if (!terminalConnected) {
      terminalConnected = true;
      return { message: JSON.stringify({ type: 'connected', session_id: 'qa-run-2' }) } as T;
    }
    return new Promise((_resolve, reject) => {
      options.signal!.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
    });
  }
  if (body.command_id === 'quote-pro') return { storage_limit: 65536 } as T;
  if (body.command_id === 'list-invoices')
    return { invoices: [{ id: 'INV-123', amount: 1250, currency: 'USD', status: 'pending' }] } as T;
  if (body.command_id === 'wait' && anchor) log.textContent = 'subscribed';
  if (body.command_id === 'wait')
    return new Promise((resolve, reject) => {
      if (location.search === '?drain' && digest.includes('aaaa')) {
        const finish = document.createElement('button');
        finish.textContent = 'Finish admitted request';
        finish.onclick = () => {
          finish.remove();
          resolve({} as T);
        };
        document.body.append(finish);
      }
      options.signal!.addEventListener('abort', () => {
        log.textContent = 'cancelled';
        reject(new DOMException('Aborted', 'AbortError'));
      });
    });
  return { payloadPresent: Object.hasOwn(body, 'payload') } as T;
};
createRoot(document.getElementById('root')!).render(
  <RichPackagePages
    scope={{ tenantId: 't', projectId: 'p' }}
    target={target}
    invokeDevice={chat ? chatRuntime.device : undefined}
    streamCommand={
      chat
        ? async (_path, body, _signal, progress) => {
            chatRuntime.record(body);
            progress({ type: 'accepted', run_id: 'cloud-run', revision: 1 });
            progress({ type: 'text_delta', text: 'reply' });
            return {};
          }
        : undefined
    }
    pathname={sandbox ? route + '?run_id=run-2&revision=8' : chat && location.search !== '?chat-desktop' ? route + '?conversationId=' +
      (location.search === '?chat-web-cloud' ? 'cloud' : 'local') : route}
    transport={transport}
    navigate={(path) => {
      if (!chat) log.textContent = path;
    }}
  />
);
