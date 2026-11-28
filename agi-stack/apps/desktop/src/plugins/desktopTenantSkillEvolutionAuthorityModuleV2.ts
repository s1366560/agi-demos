import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';
import type {
  DesktopRuntimeConfig,
  ManagedSkillEvolutionDetail,
  ManagedSkillEvolutionRun,
} from '../types';
import type { DesktopRendererGenerationActionsV2 } from './desktopRendererGenerationContextV2';
import { createDesktopTenantSkillEvolutionHttpProjectionV2 } from './desktopTenantSkillEvolutionHttpProjectionV2';
import {
  prepareSkillEvolutionInputV2,
  requireSkillEvolutionDetailV2,
  requireSkillEvolutionRunV2,
  type DesktopTenantSkillEvolutionAuthorityV2,
  type SkillEvolutionInputV2,
} from './desktopTenantSkillEvolutionOperationContractV2';
import {
  freezeSkillConfigV2,
  runSkillOperationV2,
  type SkillInputV2,
} from './desktopTenantSkillOperationSupportV2';
export const DESKTOP_TENANT_SKILL_EVOLUTION_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-skill-evolution-authority';
export const DESKTOP_TENANT_SKILL_EVOLUTION_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-skill-evolution-authority';
export const DESKTOP_TENANT_SKILL_EVOLUTION_AUTHORITY_VERSION_V2 = '1.0.0';
export interface DesktopTenantSkillEvolutionAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig): DesktopTenantSkillEvolutionAuthorityV2;
}
export interface DesktopTenantSkillEvolutionOperationsV2 {
  getTenantSkillEvolution(input: SkillEvolutionInputV2): Promise<ManagedSkillEvolutionDetail>;
  runTenantSkillEvolution(input: SkillEvolutionInputV2): Promise<ManagedSkillEvolutionRun>;
}
export interface DesktopTenantSkillEvolutionClientV2 {
  getManagedSkillEvolution(
    skillId: string,
    signal?: AbortSignal,
  ): Promise<ManagedSkillEvolutionDetail>;
  runManagedSkillEvolution(
    skillId: string,
    signal?: AbortSignal,
  ): Promise<ManagedSkillEvolutionRun>;
}
export function applyDesktopTenantSkillEvolutionAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch')
    throw new RuntimeV2Error(
      'desktop_tenant_skill_evolution_authority_config_invalid',
      'invalid skill evolution authority config',
    );
  context.provide(
    DESKTOP_TENANT_SKILL_EVOLUTION_AUTHORITY_SERVICE_V2,
    Object.freeze({ bindOperation: createDesktopTenantSkillEvolutionHttpProjectionV2 }),
  );
}
export const desktopTenantSkillEvolutionAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_TENANT_SKILL_EVOLUTION_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopTenantSkillEvolutionAuthorityV2,
});
export function createDesktopTenantSkillEvolutionOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopTenantSkillEvolutionOperationsV2 {
  const run = <T>(
    input: SkillInputV2,
    operation: (authority: DesktopTenantSkillEvolutionAuthorityV2) => Promise<T>,
  ) =>
    runSkillOperationV2(
      resolve,
      DESKTOP_TENANT_SKILL_EVOLUTION_AUTHORITY_SERVICE_V2,
      ['get', 'run'],
      input,
      operation,
    );
  return Object.freeze({
    getTenantSkillEvolution(input: SkillEvolutionInputV2) {
      const p = prepareSkillEvolutionInputV2(input);
      return run(p, async (a) =>
        requireSkillEvolutionDetailV2(await a.get(p.scope, p.skillId, p.signal), p.skillId),
      );
    },
    runTenantSkillEvolution(input: SkillEvolutionInputV2) {
      const p = prepareSkillEvolutionInputV2(input);
      return run(p, async (a) =>
        requireSkillEvolutionRunV2(await a.run(p.scope, p.skillId, p.signal), p.skillId),
      );
    },
  });
}
export function createDesktopTenantSkillEvolutionClientV2(
  operations: DesktopTenantSkillEvolutionOperationsV2,
  config: DesktopRuntimeConfig,
): DesktopTenantSkillEvolutionClientV2 {
  const frozen = freezeSkillConfigV2(config);
  const common = (signal?: AbortSignal): SkillInputV2 => ({
    config: frozen,
    scope: {
      authority: frozen.mode,
      tenantId: frozen.tenantId,
      projectId: frozen.projectId || null,
    },
    ...(signal === undefined ? {} : { signal }),
  });
  const client: DesktopTenantSkillEvolutionClientV2 = {
    getManagedSkillEvolution: (skillId, signal) =>
      operations.getTenantSkillEvolution({ ...common(signal), skillId }),
    runManagedSkillEvolution: (skillId, signal) =>
      operations.runTenantSkillEvolution({ ...common(signal), skillId }),
  };
  return Object.freeze(client);
}
function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_TENANT_SKILL_EVOLUTION_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry)
    throw new RuntimeV2Error(
      'desktop_tenant_skill_evolution_authority_catalog_missing',
      'skill evolution authority absent from catalog',
    );
  return entry.contract_digest;
}
