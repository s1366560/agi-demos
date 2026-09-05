import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist/src/plugins';

export function tenantSkillDefinitionsOperationsV2Fixture(overrides = {}) {
  const unavailable = async () => { throw new Error('tenant_skill_definitions_authority_unavailable'); };
  return Object.freeze({
    async loadTenantSkillDefinitions({ signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return [];
    },
    createTenantSkillDefinition: unavailable,
    updateTenantSkillDefinition: unavailable,
    getTenantSkillContent: unavailable,
    updateTenantSkillContent: unavailable,
    setTenantSkillStatus: unavailable,
    deleteTenantSkillDefinition: unavailable,
    ...overrides,
  });
}

export function createTenantSkillDefinitionsHttpOperationsV2Fixture(lifecycle = []) {
  const moduleV2 = require(`${ROOT}/desktopTenantSkillDefinitionsAuthorityModuleV2.js`);
  const { createDesktopTenantSkillDefinitionsHttpProjectionV2 } = require(
    `${ROOT}/desktopTenantSkillDefinitionsHttpProjectionV2.js`,
  );
  return moduleV2.createDesktopTenantSkillDefinitionsOperationsV2(() => ({
    async acquireServiceOperationLease(input) {
      lifecycle.push(['acquire', input]);
      return {
        status: 'accepted',
        async useService(callback) {
          return callback(Object.freeze({ bindOperation: createDesktopTenantSkillDefinitionsHttpProjectionV2 }));
        },
        async release() { lifecycle.push(['release']); },
      };
    },
  }));
}

export function createTenantSkillDefinitionsHttpClientV2Fixture(config, lifecycle = []) {
  const moduleV2 = require(`${ROOT}/desktopTenantSkillDefinitionsAuthorityModuleV2.js`);
  return moduleV2.createDesktopTenantSkillDefinitionsClientV2(
    createTenantSkillDefinitionsHttpOperationsV2Fixture(lifecycle), config,
  );
}

export function createTenantSkillHttpClientV2Fixture(config, lifecycle = []) {
  const clients = [createTenantSkillDefinitionsHttpClientV2Fixture(config, lifecycle)];
  for (const domain of ['Packages', 'Evolution']) {
    const moduleV2 = require(`${ROOT}/desktopTenantSkill${domain}AuthorityModuleV2.js`);
    const projection = require(`${ROOT}/desktopTenantSkill${domain}HttpProjectionV2.js`);
    const operations = moduleV2[`createDesktopTenantSkill${domain}OperationsV2`](() => ({
      async acquireServiceOperationLease(input) {
        lifecycle.push(['acquire', input]);
        return {
          status: 'accepted',
          async useService(callback) {
            return callback(Object.freeze({
              bindOperation: projection[`createDesktopTenantSkill${domain}HttpProjectionV2`],
            }));
          },
          async release() { lifecycle.push(['release']); },
        };
      },
    }));
    clients.push(moduleV2[`createDesktopTenantSkill${domain}ClientV2`](operations, config));
  }
  return Object.freeze(Object.assign({}, ...clients));
}
