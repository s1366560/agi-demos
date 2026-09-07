import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';

export function tenantSubAgentDefinitionsOperationsV2Fixture(overrides = {}) {
  const unavailable = async () => {
    throw new Error('tenant_subagent_definitions_authority_unavailable');
  };
  return Object.freeze({
    async loadTenantSubAgentDefinitions({ signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return [];
    },
    createTenantSubAgentDefinition: unavailable,
    updateTenantSubAgentDefinition: unavailable,
    setTenantSubAgentDefinitionEnabled: unavailable,
    deleteTenantSubAgentDefinition: unavailable,
    importTenantFilesystemSubAgentDefinition: unavailable,
    ...overrides,
  });
}

export function createTenantSubAgentDefinitionsHttpClientV2Fixture(config, lifecycle = []) {
  const moduleV2 = require(
    `${ROOT}/src/plugins/desktopTenantSubAgentDefinitionsAuthorityModuleV2.js`,
  );
  const { createDesktopTenantSubAgentDefinitionsHttpProjectionV2 } = require(
    `${ROOT}/src/plugins/desktopTenantSubAgentDefinitionsHttpProjectionV2.js`,
  );
  const operations = moduleV2.createDesktopTenantSubAgentDefinitionsOperationsV2(() => ({
    async acquireServiceOperationLease(input) {
      lifecycle.push(['acquire', input]);
      return {
        status: 'accepted',
        async useService(callback) {
          return callback(
            Object.freeze({
              bindOperation: createDesktopTenantSubAgentDefinitionsHttpProjectionV2,
            }),
          );
        },
        async release() {
          lifecycle.push(['release']);
        },
      };
    },
  }));
  return moduleV2.createDesktopTenantSubAgentDefinitionsClientV2(operations, config);
}
