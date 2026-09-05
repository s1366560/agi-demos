import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist/src/plugins';

export function projectMcpAppsOperationsV2Fixture(overrides = {}) {
  return Object.freeze({
    async listMCPApps({ signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return [];
    },
    ...overrides,
  });
}

export function createProjectMcpAppsHttpOperationsV2Fixture(lifecycle = []) {
  const moduleV2 = require(`${ROOT}/desktopProjectMcpAppsAuthorityModuleV2.js`);
  const { createDesktopProjectMcpAppsHttpProjectionV2 } = require(
    `${ROOT}/desktopProjectMcpAppsHttpProjectionV2.js`,
  );
  const operations = moduleV2.createDesktopProjectMcpAppsOperationsV2(() => ({
    async acquireServiceOperationLease(input) {
      lifecycle.push(['acquire', input]);
      return {
        status: 'accepted',
        async useService(callback) {
          return callback(Object.freeze({ bindOperation: createDesktopProjectMcpAppsHttpProjectionV2 }));
        },
        async release() { lifecycle.push(['release']); },
      };
    },
  }));
  return operations;
}

export function createProjectMcpAppsHttpClientV2Fixture(config, lifecycle = []) {
  const moduleV2 = require(`${ROOT}/desktopProjectMcpAppsAuthorityModuleV2.js`);
  return moduleV2.createDesktopProjectMcpAppsClientV2(
    createProjectMcpAppsHttpOperationsV2Fixture(lifecycle), config,
  );
}
