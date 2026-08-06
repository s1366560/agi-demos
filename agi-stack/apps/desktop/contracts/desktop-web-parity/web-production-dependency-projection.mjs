const DECLARATION_KEYS = Object.freeze(["routed_source_entry", "source_entry"]);
const OWNERSHIP_KEYS = Object.freeze([
  "classification",
  "owner_source_entries",
  "reason_code",
  "source_entry",
]);
const OWNERSHIP_CLASSIFICATIONS = new Set(["excluded", "owned", "shared"]);

function compareText(left, right) {
  if (left < right) {
    return -1;
  }
  if (left > right) {
    return 1;
  }
  return 0;
}

function compareEdges(left, right) {
  const targetOrder = compareText(left.to_source_entry, right.to_source_entry);
  return targetOrder !== 0
    ? targetOrder
    : compareText(left.relationship, right.relationship);
}

function assertExactDeclaration(capabilityId, declaration, index) {
  if (
    declaration === null ||
    Array.isArray(declaration) ||
    typeof declaration !== "object"
  ) {
    throw new Error(
      `Capability ${capabilityId} reviewed production dependency ${index} ` +
        "must be an exact record.",
    );
  }
  const actualKeys = Object.keys(declaration).sort();
  if (
    actualKeys.length !== DECLARATION_KEYS.length ||
    actualKeys.some((key, keyIndex) => key !== DECLARATION_KEYS[keyIndex])
  ) {
    throw new Error(
      `Capability ${capabilityId} reviewed production dependency ${index} ` +
        `must contain exactly ${DECLARATION_KEYS.join(", ")}.`,
    );
  }
  for (const fieldName of DECLARATION_KEYS) {
    if (
      typeof declaration[fieldName] !== "string" ||
      declaration[fieldName].length === 0
    ) {
      throw new Error(
        `Capability ${capabilityId} reviewed production dependency ` +
          `${fieldName} must be a non-empty string.`,
      );
    }
  }
}

function indexDependencyEdges(dependencyEdges) {
  const adjacency = new Map();
  for (const edge of dependencyEdges) {
    const edges = adjacency.get(edge.from_source_entry) ?? [];
    edges.push(edge);
    adjacency.set(edge.from_source_entry, edges);
  }
  for (const edges of adjacency.values()) {
    edges.sort(compareEdges);
  }
  return adjacency;
}

function findDependencyPath(adjacency, sourceEntry, targetEntry) {
  const pending = [{ path: [], source_entry: sourceEntry }];
  const visited = new Set([sourceEntry]);

  while (pending.length > 0) {
    const current = pending.shift();
    if (!current) {
      continue;
    }
    for (const edge of adjacency.get(current.source_entry) ?? []) {
      const nextPath = [...current.path, edge];
      if (edge.to_source_entry === targetEntry) {
        return nextPath;
      }
      if (!visited.has(edge.to_source_entry)) {
        visited.add(edge.to_source_entry);
        pending.push({
          path: nextPath,
          source_entry: edge.to_source_entry,
        });
      }
    }
  }
  return null;
}

export function assertCompleteProductionDependencyOwnership({
  auditedSourceByEntry,
  dependencyOwnership,
  dependencySourceEntries,
}) {
  if (!Array.isArray(dependencyOwnership)) {
    throw new Error("Production dependency ownership must be an array.");
  }
  if (!Array.isArray(dependencySourceEntries)) {
    throw new Error("Production dependency sources must be an array.");
  }
  const dependencyEntries = [...dependencySourceEntries].sort(compareText);
  if (new Set(dependencyEntries).size !== dependencyEntries.length) {
    throw new Error("Production dependency sources contain duplicates.");
  }
  for (const sourceEntry of dependencyEntries) {
    if (!auditedSourceByEntry.has(sourceEntry)) {
      throw new Error(
        `Production dependency source is unaudited: ${sourceEntry}.`,
      );
    }
  }
  const ownershipByEntry = new Map();

  for (const [index, ownership] of dependencyOwnership.entries()) {
    if (
      ownership === null ||
      Array.isArray(ownership) ||
      typeof ownership !== "object"
    ) {
      throw new Error(
        `Production dependency ownership ${index} must be an exact record.`,
      );
    }
    const actualKeys = Object.keys(ownership).sort(compareText);
    if (
      actualKeys.length !== OWNERSHIP_KEYS.length ||
      actualKeys.some((key, keyIndex) => key !== OWNERSHIP_KEYS[keyIndex])
    ) {
      throw new Error(
        `Production dependency ownership ${index} must contain exactly ` +
          `${OWNERSHIP_KEYS.join(", ")}.`,
      );
    }
    const {
      classification,
      owner_source_entries: ownerSourceEntries,
      reason_code: reasonCode,
      source_entry: sourceEntry,
    } = ownership;
    if (!OWNERSHIP_CLASSIFICATIONS.has(classification)) {
      throw new Error(
        `Production dependency ownership ${sourceEntry} has invalid classification.`,
      );
    }
    if (
      typeof sourceEntry !== "string" ||
      sourceEntry.length === 0 ||
      typeof reasonCode !== "string" ||
      reasonCode.length === 0 ||
      !Array.isArray(ownerSourceEntries) ||
      ownerSourceEntries.some(
        (owner) => typeof owner !== "string" || owner.length === 0,
      )
    ) {
      throw new Error(
        `Production dependency ownership ${index} contains invalid fields.`,
      );
    }
    if (!dependencyEntries.includes(sourceEntry)) {
      throw new Error(
        `Production dependency ownership references unknown source ${sourceEntry}.`,
      );
    }
    if (ownershipByEntry.has(sourceEntry)) {
      throw new Error(
        `Production dependency ownership duplicates source ${sourceEntry}.`,
      );
    }
    if (classification === "owned" && ownerSourceEntries.length !== 1) {
      throw new Error(
        `Owned production dependency ${sourceEntry} must have exactly one owner.`,
      );
    }
    if (classification === "shared" && ownerSourceEntries.length === 0) {
      throw new Error(
        `Shared production dependency ${sourceEntry} must have an owner.`,
      );
    }
    if (classification === "excluded" && ownerSourceEntries.length !== 0) {
      throw new Error(
        `Excluded production dependency ${sourceEntry} cannot have an owner.`,
      );
    }
    if (new Set(ownerSourceEntries).size !== ownerSourceEntries.length) {
      throw new Error(
        `Production dependency ownership ${sourceEntry} duplicates an owner.`,
      );
    }
    ownershipByEntry.set(sourceEntry, ownership);
  }

  const unclassifiedEntries = dependencyEntries.filter(
    (sourceEntry) => !ownershipByEntry.has(sourceEntry),
  );
  if (unclassifiedEntries.length > 0) {
    throw new Error(
      `Web inventory has unclassified production dependencies: ` +
        unclassifiedEntries.join(", "),
    );
  }
  return dependencyOwnership;
}

export function resolveReviewedProductionDependencies({
  auditedSourceByEntry,
  capabilityId,
  declarations = [],
  dependencyEdges,
  kind,
  routedSourceEntries,
}) {
  if (!Array.isArray(declarations)) {
    throw new Error(
      `Capability ${capabilityId} reviewed production dependencies must be an array.`,
    );
  }
  if (kind === "native_only") {
    if (declarations.length > 0) {
      throw new Error(
        `Native-only capability ${capabilityId} cannot declare Web production dependencies.`,
      );
    }
    return [];
  }

  const routedEntries = new Set(routedSourceEntries);
  const adjacency = indexDependencyEdges(dependencyEdges);
  const declaredPairs = new Set();

  return declarations.map((declaration, index) => {
    assertExactDeclaration(capabilityId, declaration, index);
    const {
      routed_source_entry: routedSourceEntry,
      source_entry: sourceEntry,
    } = declaration;
    const pairKey = `${routedSourceEntry}\0${sourceEntry}`;
    if (declaredPairs.has(pairKey)) {
      throw new Error(
        `Capability ${capabilityId} duplicates production dependency ${sourceEntry}.`,
      );
    }
    declaredPairs.add(pairKey);

    if (!routedEntries.has(routedSourceEntry)) {
      throw new Error(
        `Capability ${capabilityId} production dependency root ` +
          `${routedSourceEntry} is not a routed Web source.`,
      );
    }
    const auditedSource = auditedSourceByEntry.get(sourceEntry);
    if (!auditedSource?.roles?.includes("production_dependency")) {
      throw new Error(
        `Capability ${capabilityId} production dependency ${sourceEntry} ` +
          "is not an audited production dependency.",
      );
    }
    const dependencyPath = findDependencyPath(
      adjacency,
      routedSourceEntry,
      sourceEntry,
    );
    if (!dependencyPath) {
      throw new Error(
        `Capability ${capabilityId} production dependency ${sourceEntry} ` +
          `is not reachable from routed source ${routedSourceEntry}.`,
      );
    }
    return {
      dependency_path: dependencyPath,
      routed_source_entry: routedSourceEntry,
      source_entry: sourceEntry,
    };
  });
}

export function projectReviewedProductionDependencies(options) {
  const reviewedDependencies = resolveReviewedProductionDependencies(options);
  const productionSourceEntries = [
    ...new Set([
      ...options.routedSourceEntries,
      ...reviewedDependencies.flatMap((dependency) =>
        dependency.dependency_path.map((edge) => edge.to_source_entry),
      ),
    ]),
  ].sort();
  return {
    productionSourceEntries,
    reviewedDependencies,
  };
}
