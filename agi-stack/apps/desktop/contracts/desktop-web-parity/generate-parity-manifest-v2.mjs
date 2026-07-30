import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  consumeJudgment,
  indexJudgmentRecords,
  loadJudgmentRecords,
  parseManifestGeneratorOptions,
  writeValidatedArtifactSync,
} from "./parity-judgment-ledger.mjs";
import {
  apiContract,
  normalizeUnavailableDesktopContracts,
} from "./parity-contract-normalizer.mjs";
import { assertSurfacePermissionCoverage } from "./parity-permission-coverage.mjs";
import { mergeDefinitionFragments } from "./definition-fragment-merger.mjs";
import {
  bindProductionEntrySurfaces,
  validateProductionEntryIntegrity,
} from "./production-entry-integrity.mjs";
import { projectReviewedProductionDependencies } from "./web-production-dependency-projection.mjs";
import { resolveCapabilityWebEntries } from "./web-production-entry-projection.mjs";

const contractRoot = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(contractRoot, "../../../../..");
const inventoryPath = resolve(contractRoot, "web-route-inventory.v2.json");
const metadataPath = resolve(
  contractRoot,
  "parity-capability-definitions.metadata.v2.json",
);
const routeEntryPermissionCatalog = readJson(
  resolve(contractRoot, "parity-route-entry-permissions.v2.json"),
);
const definitionFragmentRegistry = readJson(
  resolve(contractRoot, "parity-capability-fragments.v2.json"),
);
const definitionFragments = definitionFragmentRegistry.fragments.map(
  (fileName) => ({
    sourceEntry: `agi-stack/apps/desktop/contracts/desktop-web-parity/${fileName}`,
    fragment: readJson(resolve(contractRoot, fileName)),
  }),
);
const manifestSourceEntry =
  "agi-stack/apps/desktop/contracts/desktop-web-parity/parity-manifest.v2.json";
const manifestPath = resolve(contractRoot, "parity-manifest.v2.json");
const cliOptions = parseManifestGeneratorOptions(process.argv.slice(2), {
  manifestPath,
  repositoryRoot,
});

const inventory = readJson(inventoryPath);
const definitions = mergeDefinitionFragments(
  readJson(metadataPath),
  definitionFragments,
);
const routeEntryPermissionsByCapability = new Map(
  routeEntryPermissionCatalog.capabilities.map((capability) => [
    capability.id,
    capability.route_entry_permissions,
  ]),
);
if (
  routeEntryPermissionsByCapability.size !==
  routeEntryPermissionCatalog.capabilities.length
) {
  throw new Error(
    "Route-entry permission catalog contains duplicate capability IDs.",
  );
}
assertExactKeys(
  routeEntryPermissionsByCapability,
  definitions.capabilities
    .filter((definition) => definition.kind === "canonical")
    .map((definition) => definition.id),
  "route-entry permission ownership",
);
const productionEntryIntegrity = validateProductionEntryIntegrity(
  definitions.production_entry_integrity,
);
if (
  inventory.source_revision !== definitions.references.web_revision ||
  inventory.source_revision !== definitions.references.audit_revision
) {
  throw new Error(
    "Web route inventory source_revision must match the audited Web revision.",
  );
}
const allRoutedSources = [
  ...inventory.lazy_page_entries,
  ...inventory.eager_route_entries,
];
const auditedSourceByEntry = new Map(
  inventory.audited_sources.map((source) => [source.source_entry, source]),
);
if (auditedSourceByEntry.size !== inventory.audited_sources.length) {
  throw new Error("Web route inventory contains duplicate audited sources.");
}
const productionRouteByKey = new Map(
  inventory.production_routes.map((route) => [route.route_key, route]),
);
if (productionRouteByKey.size !== inventory.production_routes.length) {
  throw new Error(
    "Web route inventory contains duplicate production route keys.",
  );
}

assertCount(
  inventory.canonical_navigation_targets,
  definitions.expected_counts.canonical_navigation_targets,
  "canonical navigation targets",
);
assertCount(
  inventory.production_routes,
  definitions.expected_counts.production_routes,
  "production routes",
);
assertCount(
  inventory.lazy_page_entries,
  definitions.expected_counts.lazy_page_entries,
  "lazy page entries",
);
assertCount(
  inventory.eager_route_entries,
  definitions.expected_counts.eager_route_entries,
  "eager route entries",
);

const normalizedDefinitions = definitions.capabilities.map((definition) => {
  const normalized = normalizeDefinition({
    ...definition,
    route_entry_permissions: routeEntryPermissionsByCapability.get(
      definition.id,
    ),
  });
  assertSurfacePermissionCoverage({
    capabilityId: normalized.id,
    capabilityKind: normalized.kind,
    surfaces: normalized.surfaces,
    permissionRequirements: normalized.permission_requirements,
  });
  return normalized;
});
const capabilityById = new Map(
  normalizedDefinitions.map((definition) => [definition.id, definition]),
);
if (capabilityById.size !== normalizedDefinitions.length) {
  throw new Error("Capability definitions contain duplicate IDs.");
}

const canonicalOwner = new Map(
  normalizedDefinitions.flatMap((definition) =>
    definition.web_route_ids.map((routeKey) => [routeKey, definition.id]),
  ),
);
assertExactKeys(
  canonicalOwner,
  inventory.canonical_navigation_targets.map((target) => target.route_key),
  "canonical route ownership",
);

const sourceEntryBySymbol = new Map(
  allRoutedSources.map((entry) => [entry.symbol, entry.source_entry]),
);
const sourceOwner = new Map();
for (const [capabilityId, symbols] of Object.entries(
  definitions.source_ownership,
)) {
  requireCapability(capabilityId);
  for (const symbol of symbols) {
    const sourceEntry = sourceEntryBySymbol.get(symbol);
    if (!sourceEntry) {
      throw new Error(`Unknown routed source symbol ${symbol}.`);
    }
    if (sourceOwner.has(sourceEntry)) {
      throw new Error(
        `Routed source ${sourceEntry} has multiple capability owners.`,
      );
    }
    sourceOwner.set(sourceEntry, capabilityId);
  }
}
assertExactKeys(
  sourceOwner,
  allRoutedSources.map((entry) => entry.source_entry),
  "routed source ownership",
);

const routeOwnerOverrides = new Map();
for (const [capabilityId, routeKeys] of Object.entries(
  definitions.route_owner_overrides,
)) {
  requireCapability(capabilityId);
  for (const routeKey of routeKeys) {
    if (routeOwnerOverrides.has(routeKey)) {
      throw new Error(
        `Production route ${routeKey} has multiple explicit owners.`,
      );
    }
    routeOwnerOverrides.set(routeKey, capabilityId);
  }
}

const productionRouteOwner = new Map();
for (const route of inventory.production_routes) {
  const explicitOwner = routeOwnerOverrides.get(route.route_key);
  const inferredOwners = new Set(
    route.source_entries.map((entry) => sourceOwner.get(entry.source_entry)),
  );
  inferredOwners.delete(undefined);
  const owner =
    explicitOwner ??
    (inferredOwners.size === 1 ? [...inferredOwners][0] : undefined);
  if (!owner) {
    throw new Error(
      `Production route ${route.route_key} requires an explicit audited owner.`,
    );
  }
  requireCapability(owner);
  productionRouteOwner.set(route.route_key, owner);
}
assertExactKeys(
  productionRouteOwner,
  inventory.production_routes.map((route) => route.route_key),
  "production route ownership",
);

const registrationsByCapability = groupOwnedKeys(productionRouteOwner);
const sourcesByCapability = groupOwnedKeys(sourceOwner);
const judgmentsByCapability = cliOptions.emitInputsPath
  ? new Map()
  : indexJudgmentRecords(
      loadJudgmentRecords(cliOptions, { manifestPath, repositoryRoot }),
      capabilityById.keys(),
    );
const reviewInputs = [];
const capabilities = normalizedDefinitions.map((definition) => {
  const webSources = sourcesByCapability.get(definition.id) ?? [];
  const reviewedAdditionalWebEntries =
    definition.reviewed_additional_web_entries ?? [];
  const ownedRoutes = (registrationsByCapability.get(definition.id) ?? []).map(
    (routeKey) => productionRouteByKey.get(routeKey),
  );
  const resolvedRoutedWebEntries = resolveCapabilityWebEntries({
    capabilityId: definition.id,
    kind: definition.kind,
    ownedRoutes,
    ownedSourceEntries: webSources,
    reviewedAdditionalWebEntries,
    auditedSourceEntries: auditedSourceByEntry,
    sourceOwnerByEntry: sourceOwner,
    knownCapabilityIds: capabilityById,
    webMissing: definition.web_missing,
  });
  const {
    productionSourceEntries: resolvedWebEntries,
    reviewedDependencies: webProductionDependencies,
  } = projectReviewedProductionDependencies({
    auditedSourceByEntry,
    capabilityId: definition.id,
    declarations: definition.reviewed_production_dependencies ?? [],
    dependencyEdges: inventory.production_dependency_edges,
    kind: definition.kind,
    routedSourceEntries: resolvedRoutedWebEntries,
  });
  const productionEntries = {
    web: resolvedWebEntries,
    ...bindProductionEntrySurfaces(definition.production_entries, {
      repositoryRoot,
      definitionSourcePath: definition.definition_source_entry,
      forbiddenSourcePaths: [manifestSourceEntry],
      sourceRevision: definitions.references.audit_revision,
      integrity: productionEntryIntegrity,
    }),
  };
  const auditedWebSourceEntries = new Set(
    resolvedWebEntries.filter((entry) => auditedSourceByEntry.has(entry)),
  );
  for (const routeKey of registrationsByCapability.get(definition.id) ?? []) {
    const registrationSource =
      productionRouteByKey.get(routeKey)?.registration_source;
    if (!registrationSource) {
      throw new Error(
        `Production route ${routeKey} is missing its audited registration source.`,
      );
    }
    auditedWebSourceEntries.add(registrationSource);
  }
  if (definition.web_route_ids.length > 0) {
    auditedWebSourceEntries.add("web/src/config/navigation.ts");
  }
  const auditedWebSources = [...auditedWebSourceEntries]
    .sort()
    .map((sourceEntry) => {
      const auditedSource = auditedSourceByEntry.get(sourceEntry);
      if (!auditedSource) {
        throw new Error(
          `Capability ${definition.id} references unaudited Web source ${sourceEntry}.`,
        );
      }
      return auditedSource;
    });
  const surfaces = definition.surfaces;
  const input = {
    capability_id: definition.id,
    kind: definition.kind,
    title: definition.title,
    scope: definition.scope,
    web_route_ids: definition.web_route_ids,
    web_route_registration_ids:
      registrationsByCapability.get(definition.id) ?? [],
    routed_source_entries: resolvedRoutedWebEntries,
    ...(reviewedAdditionalWebEntries.length > 0
      ? {
          reviewed_additional_web_entries: reviewedAdditionalWebEntries,
        }
      : {}),
    ...(webProductionDependencies.length > 0
      ? {
          web_production_dependencies: webProductionDependencies,
        }
      : {}),
    audited_web_sources: auditedWebSources,
    source_inventory_revisions: {
      web_routes: inventory.source_revision,
    },
    production_entry_integrity: productionEntryIntegrity,
    production_entries: productionEntries,
    api_contracts: definition.api_contracts,
    required_permissions: definition.required_permissions,
    permission_requirements: definition.permission_requirements,
    data_states: definition.data_states,
    interaction_states: definition.interaction_states,
    surfaces,
    evidence_requirements: definition.evidence_requirements,
    local_policy: definition.local_policy,
    audit_context: definition.judgment_rationale,
    audited_revision: definitions.references.audit_revision,
  };
  const inputDigest = `sha256:${digest(input)}`;
  reviewInputs.push({ input_digest: inputDigest, input });
  const judgment = cliOptions.emitInputsPath
    ? null
    : consumeJudgment({
        definition,
        input,
        inputDigest,
        surfaces,
        judgmentsByCapability,
      });
  return {
    id: definition.id,
    title: definition.title,
    domain: definition.domain,
    scope: definition.scope,
    source_revision: definitions.references.audit_revision,
    web_route_ids: definition.web_route_ids,
    web_route_registration_ids:
      registrationsByCapability.get(definition.id) ?? [],
    web_production_dependencies: webProductionDependencies,
    audited_web_sources: auditedWebSources,
    production_entries: productionEntries,
    api_contracts: definition.api_contracts,
    required_permissions: definition.required_permissions,
    route_entry_permissions: definition.route_entry_permissions,
    permission_requirements: definition.permission_requirements,
    data_states: definition.data_states,
    interaction_states: definition.interaction_states,
    expected_observable_result: definition.expected_observable_result,
    surfaces,
    evidence_requirements: definition.evidence_requirements,
    judgment,
  };
});

const manifest = {
  $schema: "./parity-manifest.v2.schema.json",
  schema_version: "2.0.0",
  references: definitions.references,
  source_inventories: {
    web_routes: {
      path: "./web-route-inventory.v2.json",
      source_revision: inventory.source_revision,
    },
    local_routes: "../local-route-parity.v1.json",
  },
  production_entry_integrity: productionEntryIntegrity,
  evidence_run_schema: "./evidence-run.v1.schema.json",
  capabilities,
};

if (cliOptions.emitInputsPath) {
  writeValidatedArtifactSync(
    cliOptions.emitInputsPath,
    `${reviewInputs.map((record) => JSON.stringify(record)).join("\n")}\n`,
    { ownerOnly: true },
  );
  console.log(
    `Prepared ${reviewInputs.length} structured Agent review inputs.`,
  );
  process.exit(0);
}

const serializedManifest = `${JSON.stringify(manifest)}\n`;
if (cliOptions.check) {
  const checkedInManifest = readFileSync(manifestPath, "utf8");
  if (checkedInManifest !== serializedManifest) {
    throw new Error(
      "parity-manifest.v2.json is stale; regenerate it with reviewed external judgments.",
    );
  }
} else {
  writeValidatedArtifactSync(cliOptions.outputPath, serializedManifest, {
    ownerOnly: cliOptions.outputOwnerOnly,
  });
}
console.log(
  `${cliOptions.check ? "Verified" : "Generated"} ${capabilities.length} capabilities, ` +
    `${productionRouteOwner.size} routes and ${sourceOwner.size} routed sources.`,
);

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}
function assertCount(items, expected, label) {
  if (items.length !== expected) {
    throw new Error(`Expected ${expected} ${label}; received ${items.length}.`);
  }
}
function assertExactKeys(actualMap, expectedKeys, label) {
  const actual = [...actualMap.keys()].sort();
  const expected = [...expectedKeys].sort();
  if (
    actual.length !== expected.length ||
    actual.some((value, index) => value !== expected[index])
  ) {
    throw new Error(`${label} does not exactly cover the audited inventory.`);
  }
}
function requireCapability(capabilityId) {
  if (!capabilityById.has(capabilityId)) {
    throw new Error(`Unknown capability owner ${capabilityId}.`);
  }
}
function groupOwnedKeys(ownership) {
  const grouped = new Map();
  for (const [key, owner] of ownership) {
    grouped.set(owner, [...(grouped.get(owner) ?? []), key]);
  }
  for (const keys of grouped.values()) keys.sort();
  return grouped;
}
function normalizeDefinition(definition) {
  const permissionRequirements = requirePermissionRequirements(definition);
  const routeEntryPermissions = requireRouteEntryPermissions(definition);
  if (definition.kind === "native_only") {
    const nativeStatus = definition.native_status ?? "implemented";
    const nativeAvailability =
      nativeStatus === "implemented" ? "available" : "degraded";
    const nativeSurface = {
      disposition: "native_only",
      implementation_status: nativeStatus,
      availability: nativeAvailability,
      reason_code:
        nativeStatus === "implemented" ? null : definition.native_reason_code,
      authority: definition.native_authority,
      allowed_actions:
        nativeStatus === "implemented"
          ? definition.actions
          : (definition.current_actions ?? []),
      intentional_deviation: definition.native_deviation ?? null,
    };
    return {
      ...definition,
      web_missing: false,
      local_policy: "native_only",
      production_entries: {
        desktop_cloud: definition.native_entries,
        desktop_local: definition.native_entries,
        native_only: definition.native_entries,
      },
      api_contracts: definition.api_contracts ?? [
        apiContract(
          "web",
          "NONE",
          `not_applicable:native-only/${definition.id}`,
          "none",
        ),
        apiContract(
          "desktop_cloud",
          definition.api_method,
          definition.api_path,
          definition.native_authority,
        ),
        apiContract(
          "desktop_local",
          definition.api_method,
          definition.api_path,
          definition.native_authority,
        ),
        apiContract(
          "native_only",
          definition.api_method,
          definition.api_path,
          definition.native_authority,
        ),
      ],
      required_permissions: definition.permissions,
      route_entry_permissions: routeEntryPermissions,
      permission_requirements: permissionRequirements,
      data_states: ["loading", "ready", "forbidden", "unavailable", "retry"],
      interaction_states: definition.interaction_states,
      expected_observable_result: definition.expected_observable_result,
      surfaces: {
        web: {
          disposition: "not_applicable",
          implementation_status: "not_applicable",
          availability: "not_applicable",
          reason_code: "native_surface_not_available_on_web",
          authority: "none",
          allowed_actions: [],
          intentional_deviation:
            "This security or lifecycle boundary exists only in the native Electron product.",
        },
        desktop_cloud: nativeSurface,
        desktop_local: nativeSurface,
        native_only: nativeSurface,
      },
      evidence_requirements: definition.evidence_requirements,
    };
  }

  const web = webSurface(definition);
  const desktopCloud = cloudSurface(definition);
  const desktopLocal = localSurface(definition);
  const localNotApplicable = definition.local_status === "not_applicable";
  return {
    ...definition,
    local_policy: definition.local_policy,
    production_entries: {
      desktop_cloud: definition.cloud_entries ?? [
        `planned:agi-stack/apps/desktop/src/routes/${definition.id}.tsx`,
      ],
      desktop_local: localNotApplicable
        ? [`not_applicable:local/${definition.id}`]
        : (definition.local_entries ?? [
            `planned:agi-stack/apps/desktop/src/routes/local/${definition.id}.tsx`,
          ]),
      native_only: [`not_applicable:native-only/${definition.id}`],
    },
    api_contracts: normalizeUnavailableDesktopContracts(
      definition.api_contracts ?? [
        apiContract(
          "web",
          definition.api_method,
          definition.api_path,
          definition.api_method === "NONE" ? "none" : "web_service",
        ),
        desktopCloud.authority === "none"
          ? apiContract(
              "desktop_cloud",
              "NONE",
              `not_applicable:${desktopCloud.reason_code}`,
              "none",
            )
          : apiContract(
              "desktop_cloud",
              definition.api_method,
              definition.api_path,
              definition.api_method === "NONE" ? "none" : "cloud_service",
            ),
        desktopLocal.authority === "none"
          ? apiContract(
              "desktop_local",
              "NONE",
              `not_applicable:${desktopLocal.reason_code}`,
              "none",
            )
          : apiContract(
              "desktop_local",
              definition.api_method,
              definition.api_path,
              definition.api_method === "NONE" ? "none" : "sidecar",
            ),
        apiContract(
          "native_only",
          "NONE",
          `not_applicable:no-native-only-api/${definition.id}`,
          "none",
        ),
      ],
      { desktop_cloud: desktopCloud, desktop_local: desktopLocal },
    ),
    required_permissions: definition.permissions,
    route_entry_permissions: routeEntryPermissions,
    permission_requirements: permissionRequirements,
    data_states: [
      "loading",
      "empty",
      "ready",
      "stale",
      "conflict",
      "forbidden",
      "unavailable",
      "retry",
    ],
    interaction_states: definition.interaction_states ?? [
      "navigate",
      "deep-link-restore",
      "scope-switch",
      "retry",
    ],
    expected_observable_result:
      definition.expected_observable_result ??
      `Cloud Desktop renders a native ${definition.title} surface with the same authority, ` +
        "permissions, data transitions, actions and structured errors as Web. Local Desktop " +
        "uses its declared sidecar policy or returns the stable unavailable reason without a " +
        "WebView or external-browser handoff.",
    surfaces: {
      web,
      desktop_cloud: desktopCloud,
      desktop_local: desktopLocal,
      native_only: surface(
        "not_applicable",
        "not_applicable",
        "not_applicable",
        "web_capability_has_no_native_only_surface",
        "none",
        [],
      ),
    },
    evidence_requirements: [
      "contract",
      "web_renderer",
      "desktop_renderer",
      "native_electron",
      "sidecar_authority",
    ],
  };
}
function cloudSurface(definition) {
  const status = definition.cloud_status;
  if (status === "implemented") {
    return surface(
      "native_equivalent",
      "implemented",
      "available",
      null,
      "cloud_service",
      definition.cloud_actions ?? definition.actions,
    );
  }
  if (status === "partial") {
    return surface(
      "native_equivalent",
      "partial",
      "degraded",
      definition.cloud_reason_code ?? "desktop_native_surface_partial",
      "cloud_service",
      definition.cloud_actions ?? definition.current_actions ?? ["view"],
    );
  }
  if (status === "planned") {
    return surface(
      "native_equivalent",
      "missing",
      "unavailable",
      "desktop_native_route_planned",
      "none",
      [],
    );
  }
  return surface(
    "native_equivalent",
    "missing",
    "unavailable",
    status === "blocked"
      ? "web_route_not_registered"
      : "desktop_native_route_planned",
    "none",
    [],
  );
}
function localSurface(definition) {
  const status = definition.local_status;
  if (status === "implemented") {
    return surface(
      "native_equivalent",
      "implemented",
      "available",
      null,
      "sidecar",
      definition.local_actions ?? definition.actions,
      definition.local_deviation,
    );
  }
  if (status === "partial") {
    return surface(
      "native_equivalent",
      "partial",
      "degraded",
      definition.local_reason_code,
      "sidecar",
      definition.local_actions ?? definition.current_actions ?? ["view"],
      definition.local_deviation,
    );
  }
  if (status === "unavailable") {
    return surface(
      "native_equivalent",
      "partial",
      "unavailable",
      definition.local_reason_code,
      "sidecar",
      [],
      definition.local_deviation,
    );
  }
  if (status === "not_applicable") {
    return surface(
      "not_applicable",
      "not_applicable",
      "not_applicable",
      definition.local_reason_code,
      "none",
      [],
      definition.local_deviation,
    );
  }
  return surface(
    "native_equivalent",
    "missing",
    "unavailable",
    status === "blocked"
      ? "web_route_not_registered"
      : (definition.local_reason_code ?? "local_native_authority_planned"),
    "none",
    [],
    definition.local_deviation,
  );
}
function webSurface(definition) {
  if (definition.web_missing) {
    return surface(
      "source_authority",
      "missing",
      "unavailable",
      "web_route_not_registered",
      "none",
      [],
    );
  }
  if (definition.web_status === "unavailable") {
    return surface(
      "source_authority",
      "unavailable",
      "unavailable",
      definition.web_reason_code,
      "web_service",
      definition.web_actions ?? [],
    );
  }
  if (definition.web_status === "partial") {
    return surface(
      "source_authority",
      "partial",
      "degraded",
      definition.web_reason_code,
      "web_service",
      definition.web_actions ?? definition.actions,
    );
  }
  return surface(
    "source_authority",
    "implemented",
    "available",
    null,
    "web_service",
    definition.web_actions ?? definition.actions,
  );
}
function surface(
  disposition,
  implementationStatus,
  availability,
  reasonCode,
  authority,
  allowedActions,
  intentionalDeviation = null,
) {
  return {
    disposition,
    implementation_status: implementationStatus,
    availability,
    reason_code: reasonCode,
    authority,
    allowed_actions: allowedActions,
    intentional_deviation: intentionalDeviation ?? null,
  };
}

function requirePermissionRequirements(definition) {
  if (
    !Object.hasOwn(definition, "permission_requirements") ||
    !Array.isArray(definition.permission_requirements) ||
    definition.permission_requirements.length === 0
  ) {
    throw new Error(
      `Capability ${definition.id} must declare reviewed permission_requirements.`,
    );
  }
  return definition.permission_requirements;
}

function requireRouteEntryPermissions(definition) {
  if (definition.kind !== "canonical") {
    return [];
  }
  if (
    !Object.hasOwn(definition, "route_entry_permissions") ||
    !Array.isArray(definition.route_entry_permissions) ||
    definition.route_entry_permissions.length === 0
  ) {
    throw new Error(
      `Capability ${definition.id} must declare reviewed route_entry_permissions.`,
    );
  }
  return definition.route_entry_permissions;
}

function dispositionSummary(surface) {
  return {
    disposition: surface.disposition,
    implementation_status: surface.implementation_status,
    availability: surface.availability,
    reason_code: surface.reason_code,
    authority: surface.authority,
  };
}

function digest(input) {
  return createHash("sha256").update(JSON.stringify(input)).digest("hex");
}

void repositoryRoot;
