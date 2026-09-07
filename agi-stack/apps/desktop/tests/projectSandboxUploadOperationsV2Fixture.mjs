import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist/src/plugins';

export function createProjectSandboxUploadHttpOperationsV2Fixture(lifecycle = []) {
  const moduleV2 = require(`${ROOT}/desktopProjectSandboxUploadAuthorityModuleV2.js`);
  const { createDesktopProjectSandboxUploadHttpProjectionV2 } = require(
    `${ROOT}/desktopProjectSandboxUploadHttpProjectionV2.js`,
  );
  const operations = moduleV2.createDesktopProjectSandboxUploadOperationsV2(() => ({
    async acquireServiceOperationLease(input) {
      lifecycle.push(['acquire', input]);
      return {
        status: 'accepted',
        async useService(callback) {
          return callback(Object.freeze({ bindOperation: createDesktopProjectSandboxUploadHttpProjectionV2 }));
        },
        async release() { lifecycle.push(['release']); },
      };
    },
  }));
  return operations;
}

export function createProjectSandboxUploadHttpClientV2Fixture(config, lifecycle = []) {
  const moduleV2 = require(`${ROOT}/desktopProjectSandboxUploadAuthorityModuleV2.js`);
  return moduleV2.createDesktopProjectSandboxUploadClientV2(
    createProjectSandboxUploadHttpOperationsV2Fixture(lifecycle), config,
  );
}
