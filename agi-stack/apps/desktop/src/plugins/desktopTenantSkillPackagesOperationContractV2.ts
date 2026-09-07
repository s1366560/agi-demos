import type {
  ManagedSkillImportInput,
  ManagedSkillZipImportInput,
  ManagedSkillLifecycle,
  ManagedSkillPackage,
  ManagedSkillVersionList,
  ManagedSkillVersionDetail,
  ManagedSkill,
} from '../types';
import { requireDesktopTenantSkillDefinitionV2 } from './desktopTenantSkillDefinitionsOperationContractV2';
import {
  freezeSkillJsonV2,
  prepareSkillInputV2,
  skillErrorV2,
  skillIdentifierV2,
  skillIntegerV2,
  skillRecordV2,
  type SkillInputV2,
  type SkillScopeV2,
} from './desktopTenantSkillOperationSupportV2';
export type SkillPackageItemInputV2 = SkillInputV2 & Readonly<{ skillId: string }>;
export type SkillPackageVersionInputV2 = SkillPackageItemInputV2 &
  Readonly<{ versionNumber: number; expectedRevision?: number }>;
export type SkillPackageImportInputV2 = SkillInputV2 & Readonly<{ input: ManagedSkillImportInput }>;
export type SkillPackageZipInputV2 = SkillInputV2 &
  Readonly<{ archive: File; input: ManagedSkillZipImportInput }>;
export interface DesktopTenantSkillPackagesAuthorityV2 {
  importPackage(
    scope: SkillScopeV2,
    input: ManagedSkillImportInput,
    signal?: AbortSignal,
  ): Promise<ManagedSkillLifecycle>;
  importZip(
    scope: SkillScopeV2,
    archive: File,
    input: ManagedSkillZipImportInput,
    signal?: AbortSignal,
  ): Promise<ManagedSkillLifecycle>;
  listVersions(
    scope: SkillScopeV2,
    skillId: string,
    signal?: AbortSignal,
  ): Promise<ManagedSkillVersionList>;
  rollback(
    scope: SkillScopeV2,
    skillId: string,
    versionNumber: number,
    expectedRevision?: number,
    signal?: AbortSignal,
  ): Promise<ManagedSkill>;
  exportPackage(
    scope: SkillScopeV2,
    skillId: string,
    signal?: AbortSignal,
  ): Promise<ManagedSkillPackage>;
  getVersion(
    scope: SkillScopeV2,
    skillId: string,
    versionNumber: number,
    signal?: AbortSignal,
  ): Promise<ManagedSkillVersionDetail>;
}
export function prepareSkillPackageItemV2(input: SkillPackageItemInputV2): SkillPackageItemInputV2 {
  return Object.freeze({
    ...prepareSkillInputV2(input),
    skillId: skillIdentifierV2(input.skillId),
  });
}
export function prepareSkillPackageVersionV2(
  input: SkillPackageVersionInputV2,
): SkillPackageVersionInputV2 {
  return Object.freeze({
    ...prepareSkillPackageItemV2(input),
    versionNumber: skillIntegerV2(input.versionNumber),
    ...(input.expectedRevision === undefined
      ? {}
      : { expectedRevision: skillIntegerV2(input.expectedRevision) }),
  });
}
export function prepareSkillPackageImportV2(
  input: SkillPackageImportInputV2,
): SkillPackageImportInputV2 {
  const common = prepareSkillInputV2(input);
  if (
    !skillRecordV2(input.input) ||
    typeof input.input.skill_md_content !== 'string' ||
    !input.input.skill_md_content.trim()
  ) {
    throw skillErrorV2('tenant_skill_package_import_invalid');
  }
  validateOptions(input.input, common.scope);
  if (
    input.input.resource_files !== undefined &&
    (!skillRecordV2(input.input.resource_files) ||
      Object.values(input.input.resource_files).some((value) => typeof value !== 'string'))
  ) {
    throw skillErrorV2('tenant_skill_package_import_invalid');
  }
  return Object.freeze({ ...common, input: freezeSkillJsonV2(input.input) });
}
export function prepareSkillPackageZipV2(input: SkillPackageZipInputV2): SkillPackageZipInputV2 {
  const common = prepareSkillInputV2(input);
  if (!(input.archive instanceof File)) throw skillErrorV2('tenant_skill_archive_invalid');
  validateOptions(input.input, common.scope);
  const archive = new File([input.archive], input.archive.name, {
    type: input.archive.type,
    lastModified: input.archive.lastModified,
  });
  return Object.freeze({ ...common, archive, input: freezeSkillJsonV2(input.input) });
}
function validateOptions(input: ManagedSkillZipImportInput, scope: SkillScopeV2): void {
  if (
    !skillRecordV2(input) ||
    (input.scope !== undefined && input.scope !== 'tenant' && input.scope !== 'project') ||
    (input.overwrite !== undefined && typeof input.overwrite !== 'boolean') ||
    (input.change_summary !== undefined &&
      input.change_summary !== null &&
      typeof input.change_summary !== 'string') ||
    (input.project_id !== undefined &&
      input.project_id !== null &&
      input.project_id !== scope.projectId) ||
    (input.scope === 'project' && scope.projectId === null)
  )
    throw skillErrorV2('tenant_skill_package_scope_invalid');
}
export function requireSkillLifecycleV2(
  value: unknown,
  scope: SkillScopeV2,
): ManagedSkillLifecycle {
  if (
    !skillRecordV2(value) ||
    typeof value.action !== 'string' ||
    !validVersion(value.version_number) ||
    !nullableString(value.version_label)
  )
    throw skillErrorV2('tenant_skill_package_response_invalid', 502);
  requireDesktopTenantSkillDefinitionV2(value.skill, scope);
  return freezeSkillJsonV2(value) as unknown as ManagedSkillLifecycle;
}
export function requireSkillPackageV2(
  value: unknown,
  scope: SkillScopeV2,
  skillId: string,
): ManagedSkillPackage {
  if (
    !skillRecordV2(value) ||
    value.format !== 'agentskills.io/skill-package' ||
    typeof value.skill_md_content !== 'string' ||
    !skillRecordV2(value.resource_files) ||
    Object.values(value.resource_files).some((item) => typeof item !== 'string') ||
    !validVersion(value.version_number) ||
    !nullableString(value.version_label)
  )
    throw skillErrorV2('tenant_skill_package_response_invalid', 502);
  requireDesktopTenantSkillDefinitionV2(value.skill, scope, skillId);
  return freezeSkillJsonV2(value) as unknown as ManagedSkillPackage;
}
export function requireSkillVersionsV2(value: unknown, skillId: string): ManagedSkillVersionList {
  if (
    !skillRecordV2(value) ||
    !Array.isArray(value.versions) ||
    !Number.isSafeInteger(value.total) ||
    Number(value.total) < value.versions.length
  ) {
    throw skillErrorV2('tenant_skill_versions_response_invalid', 502);
  }
  for (const version of value.versions) requireVersion(version, skillId);
  return freezeSkillJsonV2(value) as unknown as ManagedSkillVersionList;
}
export function requireSkillVersionV2(
  value: unknown,
  skillId: string,
  versionNumber: number,
  scope: SkillScopeV2,
): ManagedSkillVersionDetail {
  requireVersion(value, skillId);
  if (
    !skillRecordV2(value) ||
    value.version_number !== versionNumber ||
    (typeof value.skill_md_content !== 'string' &&
      !(scope.authority === 'local' && value.skill_md_content === null)) ||
    (value.resource_files !== null && !skillRecordV2(value.resource_files))
  )
    throw skillErrorV2('tenant_skill_version_response_invalid', 502);
  return freezeSkillJsonV2(value) as unknown as ManagedSkillVersionDetail;
}
function requireVersion(value: unknown, skillId: string): void {
  if (
    !skillRecordV2(value) ||
    typeof value.id !== 'string' ||
    !value.id ||
    value.skill_id !== skillId ||
    !Number.isSafeInteger(value.version_number) ||
    Number(value.version_number) < 0 ||
    !nullableString(value.version_label)
  ) {
    throw skillErrorV2('tenant_skill_version_response_invalid', 502);
  }
}
function validVersion(value: unknown): boolean {
  return value === null || (Number.isSafeInteger(value) && Number(value) >= 0);
}
function nullableString(value: unknown): boolean {
  return value === null || typeof value === 'string';
}
