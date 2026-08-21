import { canonicalJsonV2, digestV2 } from './canonical';
import { RuntimeV2Error } from './errors';
import type {
  DataPlaneTargetV2,
  EventContractV2,
  PluginModuleV2,
  ProfileEntryV2,
  ProfileSnapshotV2,
  ScopeKindV2,
  ScopeV2,
  ServiceProvidedV2,
} from './generated';
import { PLUGIN_MODULE_CATALOG_DIGEST_V2, PLUGIN_MODULE_CATALOG_V2 } from './generatedCatalog';
import { jsonSchemaValidationIssueV2 } from './schema';

export async function validateGeneratedCatalogDigestV2(): Promise<void> {
  const { catalog_digest: _digest, ...payload } = PLUGIN_MODULE_CATALOG_V2;
  const expected = `sha256:${await digestV2(payload)}`;
  if (
    PLUGIN_MODULE_CATALOG_V2.catalog_digest !== expected ||
    PLUGIN_MODULE_CATALOG_DIGEST_V2 !== expected
  ) {
    throw new RuntimeV2Error(
      'catalog_digest_mismatch',
      `generated target catalog digest mismatch: expected ${expected}`
    );
  }
}

export function generatedTargetCatalogV2(target: DataPlaneTargetV2): ReadonlyMap<string, string> {
  return new Map(
    PLUGIN_MODULE_CATALOG_V2.modules
      .filter((module) => module.targets.includes(target))
      .map((module) => [module.module_ref, module.contract_digest])
  );
}

export async function validateTargetModulesV2(
  snapshot: ProfileSnapshotV2,
  target: DataPlaneTargetV2,
  targetCatalog: ReadonlyMap<string, string>
): Promise<ReadonlyMap<string, PluginModuleV2>> {
  const modules = new Map(
    snapshot.manifests.flatMap((manifest) =>
      manifest.modules.map(
        (module) => [`${manifest.plugin_id}\0${module.module_ref}`, module] as const
      )
    )
  );
  for (const module of modules.values()) {
    if (!module.targets.includes(target)) continue;
    const catalogDigest = targetCatalog.get(module.module_ref);
    if (catalogDigest === undefined) {
      throw new RuntimeV2Error(
        'missing_target_catalog',
        `module ${module.module_ref} is absent from ${target} catalog`
      );
    }
    const expected = `sha256:${await digestV2(module.contract)}`;
    if (module.contract_digest !== expected || catalogDigest !== expected) {
      throw new RuntimeV2Error(
        'contract_digest_mismatch',
        `module ${module.module_ref} contract digest differs across manifest and catalog`
      );
    }
  }
  return modules;
}

export function preflightEntriesV2(
  entries: ReadonlyMap<string, ProfileEntryV2>,
  modules: ReadonlyMap<string, PluginModuleV2>
): void {
  const providers: Array<{
    readonly entryId: string;
    readonly isolation?: string;
    readonly provision: ServiceProvidedV2;
    readonly scope: ScopeV2;
  }> = [];
  for (const [entryId, entry] of entries) {
    const contract = requiredValue(modules, entryId, 'entry module').contract;
    const configIssue = jsonSchemaValidationIssueV2(contract.config_schema, entry.config);
    if (configIssue) {
      throw new RuntimeV2Error('invalid_module_config', `entry ${entryId} config ${configIssue}`);
    }
    validateInjects(entryId, entry, contract.services.requires);
    const declaredServices = new Set([
      ...contract.services.provides.map((item) => item.service),
      ...contract.services.requires.map((item) => item.service),
    ]);
    const unexpectedIsolation = Object.keys(entry.isolate)
      .filter((service) => !declaredServices.has(service))
      .sort();
    if (unexpectedIsolation.length > 0) {
      throw new RuntimeV2Error(
        'unexpected_isolation',
        `entry ${entryId} isolates undeclared services: ${unexpectedIsolation.join(', ')}`
      );
    }
    for (const provision of contract.services.provides) {
      const isolation = entry.isolate[provision.service];
      const conflict = providers.find(
        (item) =>
          item.provision.service === provision.service &&
          item.provision.version === provision.version &&
          item.isolation === isolation &&
          sameScope(item.scope, entry.scope)
      );
      if (conflict) {
        throw new RuntimeV2Error(
          'provider_conflict',
          `entries ${conflict.entryId} and ${entryId} provide the same service identity`
        );
      }
      providers.push({
        entryId,
        provision,
        scope: entry.scope,
        ...(isolation === undefined ? {} : { isolation }),
      });
    }
  }
}

export function eventContractCatalogV2(
  modules: Iterable<PluginModuleV2>
): ReadonlyMap<string, EventContractV2> {
  const declarations = new Map<string, EventContractV2>();
  for (const module of modules) {
    for (const declaration of [
      ...module.contract.events.emits,
      ...module.contract.events.handles,
    ]) {
      const previous = declarations.get(declaration.event);
      if (previous && eventSignature(previous) !== eventSignature(declaration)) {
        throw new RuntimeV2Error(
          'event_contract_mismatch',
          `event ${declaration.event} has inconsistent contracts`
        );
      }
      declarations.set(declaration.event, declaration);
    }
  }
  return declarations;
}

export function entryOrderV2(
  entries: ReadonlyMap<string, ProfileEntryV2>,
  modules: ReadonlyMap<string, PluginModuleV2>
): ReadonlyArray<string> {
  const dependencies = new Map<string, Set<string>>(
    Array.from(entries.keys(), (entryId) => [entryId, new Set<string>()])
  );
  for (const [entryId, entry] of entries) {
    const ownDependencies = requiredValue(dependencies, entryId, 'entry dependencies');
    if (entry.parent_entry_id !== null) ownDependencies.add(entry.parent_entry_id);
    const module = requiredValue(modules, entryId, 'entry module');
    for (const requirement of module.contract.services.requires) {
      const providers = matchingProviders(
        entries,
        modules,
        entry,
        requirement.service,
        requirement.version
      );
      const first = providers[0];
      if (!first) {
        const hasOtherVersion =
          matchingProviders(entries, modules, entry, requirement.service).length > 0;
        throw new RuntimeV2Error(
          hasOtherVersion ? 'service_version_mismatch' : 'missing_inject_provider',
          `entry ${entryId} injects missing service ${requirement.service}@${requirement.version}`
        );
      }
      const rank = scopeRank(requiredEntry(entries, first).scope);
      if (
        providers.filter((provider) => scopeRank(requiredEntry(entries, provider).scope) === rank)
          .length !== 1
      ) {
        throw new RuntimeV2Error(
          'ambiguous_inject_provider',
          `entry ${entryId} has ambiguous service ${requirement.service}`
        );
      }
      if (first !== entryId) ownDependencies.add(first);
    }
  }
  return topologicalOrder(dependencies);
}

function validateInjects(
  entryId: string,
  entry: ProfileEntryV2,
  requirementsList: PluginModuleV2['contract']['services']['requires']
): void {
  const requirements = new Map(requirementsList.map((item) => [item.alias, item]));
  const missing = [...requirements.keys()].filter((alias) => !(alias in entry.inject)).sort();
  if (missing.length > 0) {
    throw new RuntimeV2Error(
      'missing_required_inject',
      `entry ${entryId} is missing inject aliases: ${missing.join(', ')}`
    );
  }
  const unexpected = Object.keys(entry.inject)
    .filter((alias) => !requirements.has(alias))
    .sort();
  if (unexpected.length > 0) {
    throw new RuntimeV2Error(
      'unexpected_inject',
      `entry ${entryId} has unexpected inject aliases: ${unexpected.join(', ')}`
    );
  }
  for (const [alias, requirement] of requirements) {
    if (entry.inject[alias] !== requirement.service) {
      throw new RuntimeV2Error(
        'inject_service_mismatch',
        `entry ${entryId} alias ${alias} must inject ${requirement.service}`
      );
    }
  }
}

function matchingProviders(
  entries: ReadonlyMap<string, ProfileEntryV2>,
  modules: ReadonlyMap<string, PluginModuleV2>,
  consumer: ProfileEntryV2,
  service: string,
  version?: string
): string[] {
  return Array.from(modules.entries())
    .filter(
      ([providerId, module]) =>
        module.contract.services.provides.some(
          (item) => item.service === service && (version === undefined || item.version === version)
        ) &&
        scopeContains(requiredEntry(entries, providerId).scope, consumer.scope) &&
        requiredEntry(entries, providerId).isolate[service] === consumer.isolate[service]
    )
    .map(([providerId]) => providerId)
    .sort(
      (left, right) =>
        scopeRank(requiredEntry(entries, right).scope) -
        scopeRank(requiredEntry(entries, left).scope)
    );
}

function eventSignature(declaration: EventContractV2): string {
  return canonicalJsonV2({
    mode: declaration.mode,
    payload_schema: declaration.payload_schema,
    result_schema: declaration.result_schema,
  });
}

function topologicalOrder(dependencies: ReadonlyMap<string, ReadonlySet<string>>): string[] {
  const ordered: string[] = [];
  const visiting = new Set<string>();
  const visited = new Set<string>();
  const declarationRank = new Map(
    Array.from(dependencies.keys(), (entryId, index) => [entryId, index] as const)
  );
  const visit = (entryId: string): void => {
    if (visited.has(entryId)) return;
    if (visiting.has(entryId)) {
      throw new RuntimeV2Error('entry_dependency_cycle', `entry cycle includes ${entryId}`);
    }
    visiting.add(entryId);
    for (const dependency of [...(dependencies.get(entryId) ?? [])].sort(
      (left, right) =>
        requiredValue(declarationRank, left, 'entry declaration rank') -
        requiredValue(declarationRank, right, 'entry declaration rank')
    )) {
      visit(dependency);
    }
    visiting.delete(entryId);
    visited.add(entryId);
    ordered.push(entryId);
  };
  for (const entryId of dependencies.keys()) visit(entryId);
  return ordered;
}

function requiredEntry(
  entries: ReadonlyMap<string, ProfileEntryV2>,
  entryId: string
): ProfileEntryV2 {
  return requiredValue(entries, entryId, 'entry');
}

function requiredValue<K, V>(values: ReadonlyMap<K, V>, key: K, label: string): V {
  const value = values.get(key);
  if (value === undefined) throw new RuntimeV2Error('entry_order_invalid', `${label} is missing`);
  return value;
}

function scopeRank(scope: ScopeV2): number {
  const ranks: Record<ScopeKindV2, number> = {
    root: 0,
    tenant: 1,
    project: 2,
    session: 3,
  };
  return ranks[scope.kind];
}

function scopeContains(parent: ScopeV2, child: ScopeV2): boolean {
  return (
    scopeRank(parent) <= scopeRank(child) &&
    (parent.tenant_id == null || parent.tenant_id === child.tenant_id) &&
    (parent.project_id == null || parent.project_id === child.project_id) &&
    (parent.session_id == null || parent.session_id === child.session_id)
  );
}

function sameScope(left: ScopeV2, right: ScopeV2): boolean {
  return (
    left.kind === right.kind &&
    left.tenant_id === right.tenant_id &&
    left.project_id === right.project_id &&
    left.session_id === right.session_id
  );
}
