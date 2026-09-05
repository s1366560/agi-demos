import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist/src/plugins';

export function browserIntegrationOperationsV2Fixture(overrides = {}) {
  return Object.freeze({
    async listBrowserOriginGrants({ signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return [];
    },
    ...overrides,
  });
}

export function createBrowserIntegrationHttpOperationsV2Fixture(lifecycle = []) {
  const moduleV2 = require(`${ROOT}/desktopBrowserIntegrationAuthorityModuleV2.js`);
  const { createDesktopBrowserIntegrationHttpProjectionV2 } = require(
    `${ROOT}/desktopBrowserIntegrationHttpProjectionV2.js`,
  );
  const operations = moduleV2.createDesktopBrowserIntegrationOperationsV2(() => ({
    async acquireServiceOperationLease(input) {
      lifecycle.push(['acquire', input]);
      return {
        status: 'accepted',
        async useService(callback) {
          return callback(Object.freeze({ bindOperation: createDesktopBrowserIntegrationHttpProjectionV2 }));
        },
        async release() { lifecycle.push(['release']); },
      };
    },
  }));
  return operations;
}

export function createBrowserIntegrationHttpClientV2Fixture(config, lifecycle = []) {
  const moduleV2 = require(`${ROOT}/desktopBrowserIntegrationAuthorityModuleV2.js`);
  return moduleV2.createDesktopBrowserIntegrationClientV2(
    createBrowserIntegrationHttpOperationsV2Fixture(lifecycle), config,
  );
}
