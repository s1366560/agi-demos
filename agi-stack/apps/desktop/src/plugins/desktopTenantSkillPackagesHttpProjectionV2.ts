import { parseDocument } from 'yaml';
import type { DesktopRuntimeConfig, ManagedSkillImportInput } from '../types';
import { createDesktopTenantSkillDefinitionsHttpProjectionV2 } from './desktopTenantSkillDefinitionsHttpProjectionV2';
import { requireDesktopTenantSkillDefinitionsV2 } from './desktopTenantSkillDefinitionsOperationContractV2';
import type { DesktopTenantSkillPackagesAuthorityV2 } from './desktopTenantSkillPackagesOperationContractV2';
import {
  freezeSkillConfigV2,
  prepareSkillInputV2,
  requestSkillJsonV2,
  skillErrorV2,
  skillIdentifierV2,
  skillMutationBodyV2,
  skillRecordV2,
  type SkillScopeV2,
} from './desktopTenantSkillOperationSupportV2';

export function createDesktopTenantSkillPackagesHttpProjectionV2(
  config: DesktopRuntimeConfig,
): DesktopTenantSkillPackagesAuthorityV2 {
  const runtime = freezeSkillConfigV2(config);
  const query = (scope: SkillScopeV2) => {
    prepareSkillInputV2({ config: runtime, scope });
    return new URLSearchParams({ tenant_id: scope.tenantId });
  };
  const path = (skillId: string) =>
    `/api/v1/skills/${encodeURIComponent(skillIdentifierV2(skillId))}`;
  const authority: DesktopTenantSkillPackagesAuthorityV2 = {
    async importPackage(scope, input, signal) {
      const params = query(scope);
      if (runtime.mode === 'cloud')
        return (await requestSkillJsonV2(runtime, `/api/v1/skills/import?${params}`, {
          method: 'POST',
          body: input,
          signal,
        })) as Awaited<ReturnType<DesktopTenantSkillPackagesAuthorityV2['importPackage']>>;
      if (runtime.projectId) params.set('project_id', runtime.projectId);
      const resourceId = packageResourceId(input.skill_md_content);
      const definitions = createDesktopTenantSkillDefinitionsHttpProjectionV2(runtime);
      const rows = requireDesktopTenantSkillDefinitionsV2(
        await definitions.load(scope, signal),
        scope,
      );
      const resourceScope = input.scope ?? 'tenant';
      const candidates = rows.filter(
        (skill) =>
          skill.id === resourceId &&
          skill.scope === resourceScope &&
          (resourceScope === 'tenant' || skill.project_id === scope.projectId),
      );
      if (candidates.length > 1) throw skillErrorV2('managed_skill_scope_ambiguous');
      const existing = candidates[0];
      if (existing && !input.overwrite) throw skillErrorV2('managed_resource_already_exists', 409);
      const revision = existing ? existing.revision : 0;
      const body = skillMutationBodyV2(
        { ...input, full_content: input.skill_md_content },
        revision,
        resourceId,
      );
      return (await requestSkillJsonV2(runtime, `/api/v1/skills/import?${params}`, {
        method: 'POST',
        body,
        signal,
      })) as Awaited<ReturnType<DesktopTenantSkillPackagesAuthorityV2['importPackage']>>;
    },
    async importZip(scope, archive, input, signal) {
      const params = query(scope);
      if (runtime.mode === 'local')
        throw skillErrorV2('managed_resource_contract_v2_required', 501);
      const form = new FormData();
      form.append('archive', archive);
      form.append('scope', input.scope ?? 'tenant');
      form.append('overwrite', String(input.overwrite ?? false));
      if (input.project_id) form.append('project_id', input.project_id);
      if (input.change_summary) form.append('change_summary', input.change_summary);
      return (await requestSkillJsonV2(runtime, `/api/v1/skills/import/zip?${params}`, {
        method: 'POST',
        body: form,
        signal,
      })) as Awaited<ReturnType<DesktopTenantSkillPackagesAuthorityV2['importZip']>>;
    },
    async listVersions(scope, skillId, signal) {
      const params = query(scope);
      params.set('limit', '50');
      return (await requestSkillJsonV2(runtime, `${path(skillId)}/versions?${params}`, {
        signal,
      })) as Awaited<ReturnType<DesktopTenantSkillPackagesAuthorityV2['listVersions']>>;
    },
    async rollback(scope, skillId, versionNumber, expectedRevision, signal) {
      const params = query(scope);
      const body =
        runtime.mode === 'local'
          ? skillMutationBodyV2(null, expectedRevision, undefined, versionNumber)
          : { version_number: versionNumber };
      return (await requestSkillJsonV2(runtime, `${path(skillId)}/rollback?${params}`, {
        method: 'POST',
        body,
        signal,
      })) as Awaited<ReturnType<DesktopTenantSkillPackagesAuthorityV2['rollback']>>;
    },
    async exportPackage(scope, skillId, signal) {
      const params = query(scope);
      return (await requestSkillJsonV2(runtime, `${path(skillId)}/export?${params}`, {
        signal,
      })) as Awaited<ReturnType<DesktopTenantSkillPackagesAuthorityV2['exportPackage']>>;
    },
    async getVersion(scope, skillId, versionNumber, signal) {
      const params = query(scope);
      return (await requestSkillJsonV2(
        runtime,
        `${path(skillId)}/versions/${versionNumber}?${params}`,
        { signal },
      )) as Awaited<ReturnType<DesktopTenantSkillPackagesAuthorityV2['getVersion']>>;
    },
  };
  return Object.freeze(authority);
}
function packageResourceId(content: ManagedSkillImportInput['skill_md_content']): string {
  const lines = content.split(/\r?\n/);
  const closing = lines.slice(1).findIndex((line) => line === '---');
  if (lines[0] !== '---' || closing < 0) throw skillErrorV2('invalid_skill_package');
  let value: unknown;
  try {
    const document = parseDocument(lines.slice(1, closing + 1).join('\n'), {
      customTags: [],
      logLevel: 'silent',
      merge: false,
      prettyErrors: false,
      resolveKnownTags: false,
      schema: 'core',
      strict: true,
      stringKeys: true,
      uniqueKeys: true,
      version: '1.2',
    });
    if (document.errors.length || document.warnings.length)
      throw skillErrorV2('invalid_skill_package');
    value = document.toJS({ maxAliasCount: 0 });
  } catch {
    throw skillErrorV2('invalid_skill_package');
  }
  const id = skillRecordV2(value) && typeof value.name === 'string' ? value.name.trim() : '';
  if (
    !id ||
    new TextEncoder().encode(id).length > 200 ||
    id.includes('/') ||
    id.includes('\\') ||
    id === '.' ||
    id === '..'
  ) {
    throw skillErrorV2('invalid_managed_resource_id');
  }
  return id;
}
