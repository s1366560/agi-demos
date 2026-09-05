import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist/src/plugins';

export function createProjectSandboxSurfaceHttpOperationsV2Fixture(lifecycle = []) {
  const moduleV2 = require(`${ROOT}/desktopProjectSandboxSurfaceAuthorityModuleV2.js`);
  const { createDesktopProjectSandboxSurfaceHttpProjectionV2 } = require(
    `${ROOT}/desktopProjectSandboxSurfaceHttpProjectionV2.js`,
  );
  return moduleV2.createDesktopProjectSandboxSurfaceOperationsV2(() => ({
    async acquireServiceOperationLease(input) {
      lifecycle.push(['acquire', input]);
      return {
        status: 'accepted',
        async useService(callback) {
          return callback(Object.freeze({
            bindOperation: createDesktopProjectSandboxSurfaceHttpProjectionV2,
          }));
        },
        async release() { lifecycle.push(['release']); },
      };
    },
  }));
}

export function createProjectSandboxSurfaceHttpClientV2Fixture(config, lifecycle = []) {
  const moduleV2 = require(`${ROOT}/desktopProjectSandboxSurfaceAuthorityModuleV2.js`);
  return moduleV2.createDesktopProjectSandboxSurfaceClientV2(
    createProjectSandboxSurfaceHttpOperationsV2Fixture(lifecycle), config,
  );
}

export function createProjectSandboxSurfaceFileClientV2Fixture(config, capabilities) {
  const client = createProjectSandboxSurfaceHttpClientV2Fixture(config);
  const snapshot = { service_version: '0.1.0', contract_version: 2, ...capabilities };
  return Object.freeze({
    listFiles: (request, signal) => client.listFiles(snapshot, request, signal),
    readFile: (request, signal) => client.readFile(snapshot, request, signal),
    downloadFile: (request, signal) => client.downloadFile(snapshot, request, signal),
  });
}
