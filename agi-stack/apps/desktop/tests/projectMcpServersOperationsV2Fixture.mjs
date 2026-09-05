import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist/src/plugins';

export function projectMcpServersOperationsV2Fixture(overrides = {}) {
  return Object.freeze({
    async listMCPServers({ signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return [];
    },
    ...overrides,
  });
}

export function createProjectMcpServersHttpOperationsV2Fixture(lifecycle = []) {
  const moduleV2 = require(`${ROOT}/desktopProjectMcpServersAuthorityModuleV2.js`);
  const { createDesktopProjectMcpServersHttpProjectionV2 } = require(
    `${ROOT}/desktopProjectMcpServersHttpProjectionV2.js`,
  );
  const operations = moduleV2.createDesktopProjectMcpServersOperationsV2(() => ({
    async acquireServiceOperationLease(input) {
      lifecycle.push(['acquire', input]);
      return {
        status: 'accepted',
        async useService(callback) {
          return callback(Object.freeze({ bindOperation: createDesktopProjectMcpServersHttpProjectionV2 }));
        },
        async release() { lifecycle.push(['release']); },
      };
    },
  }));
  return operations;
}

export function createProjectMcpServersHttpClientV2Fixture(config, lifecycle = []) {
  const moduleV2 = require(`${ROOT}/desktopProjectMcpServersAuthorityModuleV2.js`);
  return moduleV2.createDesktopProjectMcpServersClientV2(
    createProjectMcpServersHttpOperationsV2Fixture(lifecycle), config,
  );
}
