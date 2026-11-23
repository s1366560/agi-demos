import { agentChatRuntime } from './agentChatRuntime';
import { createRoot } from 'react-dom/client';
import { RichPackagePages } from '../../../agi-stack/packages/plugin-marketplace-ui/src/RichPackagePages';
import type { MarketplaceTransport } from '../../../agi-stack/packages/plugin-marketplace-ui/src/client';

const route = '/qa-page';
let digest = 'sha256:' + 'a'.repeat(64);
let corrupt = location.search === '?bad';
const chat = location.search.startsWith('?chat');
const target = chat && location.search !== '?chat-web' ? 'desktop-renderer' : 'web';
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
const source = chat
  ? (await import('../../../plugins/business/agent/ui/chat.js?raw')).default
  : sandbox
    ? (await import('../../../plugins/business/environments/ui/sandbox.js?raw')).default
    : billing
      ? (await import('../../../plugins/business/billing/ui/account.js?raw')).default
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
      items: [{ plugin_id: 'qa', actual_digest: digest, status: 'enabled', pages: [descriptor] }],
    } as T;
  if (path.includes('/ui?'))
    return {
      ...descriptor,
      schema: 'memstack.rich-page/1',
      navigation_routes: [route, '/project/:projectId/details/:id'],
      release_digest: digest,
      target,
      commands: chat
        ? ['chat-create', 'chat-list', 'chat-history', 'chat-turn', 'chat-cancel']
        : sandbox
          ? ['sandbox-status', 'prepare-sandbox', 'authorize-run-terminal']
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
  if (chat)
    return chatRuntime.command(body.command_id, body.payload as Record<string, unknown>) as T;
  if (body.command_id === 'sandbox-status') {
    const degraded = location.search === '?sandbox-degraded';
    return {
      sandbox: { sandbox_id: 'dev', status: 'running' },
      terminal: {
        availability: degraded ? 'degraded' : 'available',
        reason_code: degraded ? 'terminal_authority_unavailable' : null,
      },
    } as T;
  }
  if (body.command_id === 'authorize-run-terminal') {
    log.textContent = JSON.stringify(body.payload);
    return { expires_at: '2030-10-01T00:00:00Z' } as T;
  }
  if (body.command_id === 'quote-pro') return { storage_limit: 65536 } as T;
  if (body.command_id === 'list-invoices')
    return { invoices: [{ id: 'INV-123', amount: 1250, currency: 'USD', status: 'pending' }] } as T;
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
    pathname={route}
    transport={transport}
    navigate={(path) => {
      log.textContent = path;
    }}
  />
);
