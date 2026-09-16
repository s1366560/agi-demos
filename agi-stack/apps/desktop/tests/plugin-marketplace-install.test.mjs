import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const COMPILED = '/tmp/agistack-desktop-test-dist';
const {
  buildMarketplaceInstallRequest,
  marketplaceInstallAvailability,
  marketplacePluginPermissions,
} = require(`${COMPILED}/src/api/pluginMarketplaceModel.js`);
const { DesktopApiClient } = require(`${COMPILED}/src/api/client.js`);
const { DEFAULT_CONFIG } = require(`${COMPILED}/src/types.js`);

const signedEntry = {
  plugin_id: 'release/notifier',
  version: '2.4.1',
  publisher: 'MemStack Labs',
  artifact_digest: 'a'.repeat(64),
  artifact_registry: 'https://registry.example.test',
  artifact_repository: 'plugins/release-notifier',
  oci_manifest_digest: 'b'.repeat(64),
  install_status: 'uninstalled',
  manifest: {
    targets: ['python'],
    signature: 'c2ln',
    manifests: [
      { permissions: ['tools.execute', 'network.egress'] },
      { permissions: ['tools.execute'] },
    ],
  },
  signature: { algorithm: 'Ed25519', public_key_pem: 'pem-public', signature_base64: 'c2ln' },
  provenance: {
    predicateType: 'https://slsa.dev/provenance/v1',
    builderId: 'builder-v2',
    subjectName: 'release/notifier',
  },
  security_scan_status: 'passed',
  revoked: false,
  revocation_reason: null,
};

test('install availability distinguishes ready, installed, revoked, scan, unsigned and local', () => {
  assert.equal(marketplaceInstallAvailability('cloud', signedEntry), 'ready');
  assert.equal(
    marketplaceInstallAvailability('cloud', { ...signedEntry, install_status: 'installed' }),
    'installed',
  );
  assert.equal(
    marketplaceInstallAvailability('cloud', { ...signedEntry, revoked: true }),
    'revoked',
  );
  assert.equal(
    marketplaceInstallAvailability('cloud', { ...signedEntry, security_scan_status: 'pending' }),
    'scan_pending',
  );
  assert.equal(
    marketplaceInstallAvailability('cloud', {
      ...signedEntry,
      signature: { algorithm: 'Ed25519' },
      provenance: { builder_id: 'builder-v2' },
    }),
    'unsigned',
  );
  assert.equal(marketplaceInstallAvailability('local', signedEntry), 'local_unavailable');
});

test('declared permissions are collected from bundle manifests, deduplicated and sorted', () => {
  assert.deepEqual(marketplacePluginPermissions(signedEntry.manifest), [
    'network.egress',
    'tools.execute',
  ]);
  assert.deepEqual(marketplacePluginPermissions({}), []);
});

test('install request pins the exact protocol-v2 contract shape', () => {
  const request = buildMarketplaceInstallRequest(signedEntry, 'tenant-1');
  assert.deepEqual(request, {
    plugin_id: 'release/notifier',
    version: '2.4.1',
    publisher: 'MemStack Labs',
    tenant_id: 'tenant-1',
    artifact: {
      registry: 'https://registry.example.test',
      repository: 'plugins/release-notifier',
      manifest_sha256: 'b'.repeat(64),
    },
    artifact_sha256: 'a'.repeat(64),
    manifest: signedEntry.manifest,
    signature: {
      algorithm: 'Ed25519',
      public_key_pem: 'pem-public',
      signature_base64: 'c2ln',
    },
    provenance: {
      predicate_type: 'https://slsa.dev/provenance/v1',
      builder_id: 'builder-v2',
      subject_name: 'release/notifier',
    },
    approved_permissions: ['network.egress', 'tools.execute'],
    tenant_admin_approved: true,
    security_scan_passed: true,
  });
});

test('install request falls back to snake_case provenance and manifest signature', () => {
  const request = buildMarketplaceInstallRequest(
    {
      ...signedEntry,
      signature: { public_key_pem: 'pem-public' },
      provenance: {
        predicate_type: 'https://slsa.dev/provenance/v1',
        builder_id: 'builder-v2',
        subject_name: 'release/notifier',
      },
    },
    'tenant-1',
  );
  assert.equal(request?.signature.signature_base64, 'c2ln');
  assert.equal(request?.provenance.builder_id, 'builder-v2');
  assert.equal(
    buildMarketplaceInstallRequest(signedEntry, '  '),
    null,
  );
});

test('client install, approve and revoke hit exact V2 endpoints with contract bodies', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    const url = String(input);
    const payload = url.endsWith('/install')
      ? { plugin_id: 'release/notifier', version: '2.4.1', status: 'approved', reason: 'ok' }
      : url.endsWith('/approve')
        ? {
            plugin_id: 'release/notifier',
            version: '2.4.1',
            status: 'approved',
            granted_permissions: ['tools.execute'],
          }
        : { plugin_id: 'release/notifier', revoked_versions: ['2.4.1'], revoked_permissions: 2 };
    return new Response(JSON.stringify(payload), {
      status: url.endsWith('/install') ? 202 : 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      localApiToken: 'local-session-token',
      tenantId: 'tenant-1',
    });
    const request = buildMarketplaceInstallRequest(signedEntry, 'tenant-1');
    const installed = await client.installMarketplacePlugin(request);
    const approved = await client.approveMarketplacePlugin('release/notifier', {
      version: '2.4.1',
      approvedPermissions: ['tools.execute'],
    });
    const revoked = await client.revokeMarketplacePlugin('release/notifier', {
      reason: 'publisher compromised',
    });

    assert.equal(installed.status, 'approved');
    assert.deepEqual(approved.granted_permissions, ['tools.execute']);
    assert.deepEqual(revoked.revoked_versions, ['2.4.1']);
    assert.deepEqual(
      calls.map((call) => [call.input, call.init?.method]),
      [
        [
          'http://127.0.0.1:8088/api/v1/plugin-marketplace/packages/release%2Fnotifier/install',
          'POST',
        ],
        [
          'http://127.0.0.1:8088/api/v1/plugin-marketplace/packages/release%2Fnotifier/approve',
          'POST',
        ],
        [
          'http://127.0.0.1:8088/api/v1/plugin-marketplace/packages/release%2Fnotifier/revoke',
          'POST',
        ],
      ],
    );
    assert.deepEqual(JSON.parse(calls[0].init.body), request);
    assert.deepEqual(JSON.parse(calls[1].init.body), {
      version: '2.4.1',
      tenant_id: 'tenant-1',
      approved_permissions: ['tools.execute'],
    });
    assert.deepEqual(JSON.parse(calls[2].init.body), { reason: 'publisher compromised' });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('client install refuses tenant scope drift before any request', async () => {
  const client = new DesktopApiClient({
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:8088',
    localApiToken: 'local-session-token',
    tenantId: 'tenant-1',
  });
  const drifted = buildMarketplaceInstallRequest(signedEntry, 'tenant-2');
  await assert.rejects(client.installMarketplacePlugin(drifted), /tenant scope mismatch/i);
});

// Interactive UI states: permission gate, unavailable gate, busy, success,
// quarantined (structured reason) and transport error.
const webRequire = createRequire(new URL('../../../../web/package.json', import.meta.url));
const { Window } = await import(pathToFileURL(webRequire.resolve('happy-dom')).href);
const window = new Window({ url: 'http://localhost/' });
for (const key of [
  'window',
  'document',
  'navigator',
  'HTMLElement',
  'Element',
  'Node',
  'MutationObserver',
  'getComputedStyle',
  'requestAnimationFrame',
  'cancelAnimationFrame',
]) {
  const value = key === 'window' ? window : window[key];
  Object.defineProperty(globalThis, key, {
    configurable: true,
    value:
      typeof value === 'function' &&
      ['getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame'].includes(key)
        ? value.bind(window)
        : value,
  });
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = require('react');
const { act } = React;
const { createRoot } = require('react-dom/client');
const esbuild = createRequire(require.resolve('vite'))('esbuild');
const compiled = await esbuild.build({
  stdin: {
    contents:
      "export { usePluginManagement } from './src/features/settings/usePluginManagement'; export { PluginInstallDialog } from './src/features/settings/PluginManagementDialogs'; export { I18nProvider } from './src/i18n';",
    resolveDir: new URL('..', import.meta.url).pathname,
    loader: 'ts',
  },
  write: false,
  bundle: true,
  platform: 'node',
  format: 'cjs',
  packages: 'external',
  loader: { '.css': 'empty', '.svg': 'text' },
  define: { 'import.meta.env.DEV': 'false', 'import.meta.env.PROD': 'true' },
});
const module = { exports: {} };
new Function('require', 'module', 'exports', compiled.outputFiles[0].text)(
  (name) => {
    const value = require(name);
    return value?.[Symbol.toStringTag] === 'Module' ? { ...value, __esModule: true } : value;
  },
  module,
  module.exports,
);
const { usePluginManagement, PluginInstallDialog, I18nProvider } = module.exports;

const managedPlugin = { ...signedEntry, id: 'release/notifier@2.4.1', name: 'release/notifier' };
const cloudConfig = {
  ...DEFAULT_CONFIG,
  apiBaseUrl: 'http://127.0.0.1:8088',
  localApiToken: 'local-session-token',
  tenantId: 'tenant-1',
  mode: 'cloud',
};

const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
};

function Harness({ config, operations, canManage, plugin, onReload }) {
  const management = usePluginManagement({
    active: true,
    config,
    pluginMarketplaceOperationsV2: operations,
    contextKey: 'ctx-1',
    canManage,
    onReload,
    onUninstalled: () => {},
  });
  return React.createElement(
    React.Fragment,
    null,
    React.createElement(
      'button',
      {
        'data-testid': 'open-install',
        onClick: () => management.openInstall(plugin),
      },
      'open',
    ),
    management.dialog?.kind === 'install'
      ? React.createElement(PluginInstallDialog, {
          plugin: management.dialog.plugin,
          busy: management.dialogBusy,
          error: management.dialogError,
          onClose: management.closeDialog,
          onInstall: () => void management.install(),
        })
      : null,
    React.createElement('span', { 'data-testid': 'busy' }, String(management.dialogBusy)),
    React.createElement('span', { 'data-testid': 'error' }, management.dialogError ?? ''),
  );
}

async function mount(props) {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(React.createElement(I18nProvider, null, React.createElement(Harness, props)));
  });
  return { container, root };
}

const openInstall = async (container) => {
  await act(async () => {
    container.querySelector('[data-testid="open-install"]').click();
  });
};
const approveAndConfirm = async (container) => {
  const checkbox = container.querySelector('input[type="checkbox"]');
  await act(async () => {
    checkbox.click();
  });
  const confirm = [...container.querySelectorAll('button')].find((button) =>
    button.textContent.includes('Install plugin'),
  );
  await act(async () => {
    confirm.click();
  });
};

test('install dialog is hidden for non-privileged callers and unavailable entries', async () => {
  for (const [canManage, plugin] of [
    [false, managedPlugin],
    [true, { ...managedPlugin, revoked: true }],
    [true, { ...managedPlugin, signature: { algorithm: 'Ed25519' } }],
  ]) {
    const { container, root } = await mount({
      config: cloudConfig,
      operations: {},
      canManage,
      plugin,
      onReload: async () => {},
    });
    await openInstall(container);
    assert.equal(container.querySelector('[role="dialog"]'), null);
    root.unmount();
    container.remove();
  }
});

test('local mode fails closed: install action never opens a dialog', async () => {
  const { container, root } = await mount({
    config: { ...cloudConfig, mode: 'local' },
    operations: {},
    canManage: true,
    plugin: managedPlugin,
    onReload: async () => {},
  });
  await openInstall(container);
  assert.equal(container.querySelector('[role="dialog"]'), null);
  root.unmount();
  container.remove();
});

test('install dialog requires permission approval, then shows busy and closes on approval', async () => {
  const pending = deferred();
  const calls = [];
  let reloads = 0;
  const operations = {
    installMarketplacePlugin: async (config, request) => {
      calls.push(request);
      return pending.promise;
    },
  };
  const { container, root } = await mount({
    config: cloudConfig,
    operations,
    canManage: true,
    plugin: managedPlugin,
    onReload: async () => {
      reloads += 1;
    },
  });
  await openInstall(container);
  const dialog = container.querySelector('[role="dialog"]');
  assert.ok(dialog);
  assert.match(dialog.textContent, /tools\.execute/);
  assert.match(dialog.textContent, /network\.egress/);
  const confirm = [...dialog.querySelectorAll('button')].find((button) =>
    button.textContent.includes('Install plugin'),
  );
  assert.equal(confirm.disabled, true);

  await approveAndConfirm(container);
  assert.equal(container.querySelector('[data-testid="busy"]').textContent, 'true');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].tenant_id, 'tenant-1');
  assert.equal(calls[0].signature.public_key_pem, 'pem-public');

  await act(async () => {
    pending.resolve({
      plugin_id: 'release/notifier',
      version: '2.4.1',
      status: 'approved',
      reason: 'protocol v2 Bundle verified and desired',
    });
  });
  assert.equal(container.querySelector('[role="dialog"]'), null);
  assert.equal(reloads, 1);
  root.unmount();
  container.remove();
});

test('quarantined decision keeps the dialog open with the structured reason', async () => {
  const operations = {
    installMarketplacePlugin: async () => ({
      plugin_id: 'release/notifier',
      version: '2.4.1',
      status: 'quarantined',
      reason: 'protocol v2 marketplace trust store is empty',
    }),
  };
  const { container, root } = await mount({
    config: cloudConfig,
    operations,
    canManage: true,
    plugin: managedPlugin,
    onReload: async () => {},
  });
  await openInstall(container);
  await approveAndConfirm(container);
  assert.ok(container.querySelector('[role="dialog"]'));
  assert.equal(
    container.querySelector('[data-testid="error"]').textContent,
    'protocol v2 marketplace trust store is empty',
  );
  root.unmount();
  container.remove();
});

test('transport failure surfaces an honest structured error and recovers', async () => {
  const operations = {
    installMarketplacePlugin: async () => {
      throw new Error('Only a platform administrator may install a marketplace package');
    },
  };
  const { container, root } = await mount({
    config: cloudConfig,
    operations,
    canManage: true,
    plugin: managedPlugin,
    onReload: async () => {},
  });
  await openInstall(container);
  await approveAndConfirm(container);
  assert.ok(container.querySelector('[role="dialog"]'));
  assert.equal(
    container.querySelector('[data-testid="error"]').textContent,
    'Only a platform administrator may install a marketplace package',
  );
  assert.equal(container.querySelector('[data-testid="busy"]').textContent, 'false');
  root.unmount();
  container.remove();
});
