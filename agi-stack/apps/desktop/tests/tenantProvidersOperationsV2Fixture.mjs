import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist/src/plugins';

export function tenantProvidersOperationsV2Fixture(overrides = {}) {
  return Object.freeze({
    async listLlmProviders({ signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return [];
    },
    async listLlmProviderTypes({ signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return [];
    },
    ...overrides,
  });
}

export function createTenantProvidersHttpOperationsV2Fixture(lifecycle = []) {
  const moduleV2 = require(`${ROOT}/desktopTenantProvidersAuthorityModuleV2.js`);
  const { createDesktopTenantProvidersHttpProjectionV2 } = require(
    `${ROOT}/desktopTenantProvidersHttpProjectionV2.js`,
  );
  const operations = moduleV2.createDesktopTenantProvidersOperationsV2(() => ({
    async acquireServiceOperationLease(input) {
      lifecycle.push(['acquire', input]);
      return {
        status: 'accepted',
        async useService(callback) {
          return callback(Object.freeze({ bindOperation: createDesktopTenantProvidersHttpProjectionV2 }));
        },
        async release() { lifecycle.push(['release']); },
      };
    },
  }));
  return operations;
}

export function createTenantProvidersHttpClientV2Fixture(config, lifecycle = []) {
  const moduleV2 = require(`${ROOT}/desktopTenantProvidersAuthorityModuleV2.js`);
  return moduleV2.createDesktopTenantProvidersClientV2(
    createTenantProvidersHttpOperationsV2Fixture(lifecycle), config,
  );
}
