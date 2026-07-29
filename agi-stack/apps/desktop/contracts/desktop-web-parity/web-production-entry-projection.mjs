const REVIEWED_ADDITIONAL_WEB_ENTRY_KEYS = Object.freeze([
  "relationship",
  "route_registration_id",
  "source_entry",
  "source_owner_capability_id",
]);
const CANONICAL_REDIRECT_TARGET = "canonical_redirect_target";

export function resolveCapabilityWebEntries({
  capabilityId,
  kind,
  ownedRoutes,
  ownedSourceEntries,
  reviewedAdditionalWebEntries = [],
  auditedSourceEntries = new Set(),
  sourceOwnerByEntry = new Map(),
  knownCapabilityIds = new Set(),
  webMissing,
}) {
  if (!Array.isArray(reviewedAdditionalWebEntries)) {
    throw new Error(
      `Capability ${capabilityId} reviewed additional Web entries must be an array.`,
    );
  }
  if (kind === "native_only") {
    if (reviewedAdditionalWebEntries.length > 0) {
      throw new Error(
        `Native-only capability ${capabilityId} cannot share Web production entries.`,
      );
    }
    return [`not_applicable:web/${capabilityId}`];
  }

  const entries = new Set(ownedSourceEntries);
  for (const route of ownedRoutes) {
    for (const source of route.source_entries) {
      entries.add(source.source_entry);
    }
  }
  for (const sourceEntry of validateReviewedAdditionalWebEntries({
    capabilityId,
    declarations: reviewedAdditionalWebEntries,
    ownedRoutes,
    ownedSourceEntries,
    auditedSourceEntries,
    sourceOwnerByEntry,
    knownCapabilityIds,
  })) {
    entries.add(sourceEntry);
  }
  if (entries.size > 0) {
    return [...entries].sort();
  }
  if (webMissing) {
    return [`not_applicable:web-route-missing/${capabilityId}`];
  }
  return ["web/src/App.tsx"];
}

function validateReviewedAdditionalWebEntries({
  capabilityId,
  declarations,
  ownedRoutes,
  ownedSourceEntries,
  auditedSourceEntries,
  sourceOwnerByEntry,
  knownCapabilityIds,
}) {
  const ownedRouteIds = new Set(ownedRoutes.map((route) => route.route_key));
  const alreadyProjectedEntries = new Set(ownedSourceEntries);
  for (const route of ownedRoutes) {
    for (const source of route.source_entries) {
      alreadyProjectedEntries.add(source.source_entry);
    }
  }
  const reviewedSourceEntries = new Set();

  return declarations.map((declaration, index) => {
    if (
      declaration === null ||
      Array.isArray(declaration) ||
      typeof declaration !== "object"
    ) {
      throw new Error(
        `Capability ${capabilityId} reviewed Web entry ${index} must be an exact record.`,
      );
    }
    assertExactDeclarationKeys(capabilityId, declaration, index);

    const {
      relationship,
      route_registration_id: routeRegistrationId,
      source_entry: sourceEntry,
      source_owner_capability_id: sourceOwnerCapabilityId,
    } = declaration;
    for (const [fieldName, value] of Object.entries({
      relationship,
      route_registration_id: routeRegistrationId,
      source_entry: sourceEntry,
      source_owner_capability_id: sourceOwnerCapabilityId,
    })) {
      if (typeof value !== "string" || value.length === 0) {
        throw new Error(
          `Capability ${capabilityId} reviewed Web entry ${fieldName} ` +
            "must be a non-empty string.",
        );
      }
    }
    if (relationship !== CANONICAL_REDIRECT_TARGET) {
      throw new Error(
        `Capability ${capabilityId} reviewed Web entry relationship must be ` +
          `${CANONICAL_REDIRECT_TARGET}.`,
      );
    }
    if (!ownedRouteIds.has(routeRegistrationId)) {
      throw new Error(
        `Capability ${capabilityId} does not own production route ` +
          `${routeRegistrationId}.`,
      );
    }
    if (!auditedSourceEntries.has(sourceEntry)) {
      throw new Error(
        `Capability ${capabilityId} additional Web entry ${sourceEntry} ` +
          "is not an audited routed source.",
      );
    }
    if (!knownCapabilityIds.has(sourceOwnerCapabilityId)) {
      throw new Error(
        `Capability ${capabilityId} declares unknown source owner ` +
          `${sourceOwnerCapabilityId}.`,
      );
    }
    const actualSourceOwner = sourceOwnerByEntry.get(sourceEntry);
    if (actualSourceOwner !== sourceOwnerCapabilityId) {
      throw new Error(
        `Capability ${capabilityId} additional Web entry ${sourceEntry} owner ` +
          `mismatch: declared ${sourceOwnerCapabilityId}, audited ` +
          `${String(actualSourceOwner)}.`,
      );
    }
    if (sourceOwnerCapabilityId === capabilityId) {
      throw new Error(
        `Capability ${capabilityId} cannot additionally share its own source entry ` +
          `${sourceEntry}.`,
      );
    }
    if (alreadyProjectedEntries.has(sourceEntry)) {
      throw new Error(
        `Capability ${capabilityId} additional Web entry ${sourceEntry} is redundant.`,
      );
    }
    if (reviewedSourceEntries.has(sourceEntry)) {
      throw new Error(
        `Capability ${capabilityId} duplicates source entry ${sourceEntry}.`,
      );
    }
    reviewedSourceEntries.add(sourceEntry);
    return sourceEntry;
  });
}

function assertExactDeclarationKeys(capabilityId, declaration, index) {
  const actualKeys = Object.keys(declaration).sort();
  if (
    actualKeys.length !== REVIEWED_ADDITIONAL_WEB_ENTRY_KEYS.length ||
    actualKeys.some(
      (key, keyIndex) => key !== REVIEWED_ADDITIONAL_WEB_ENTRY_KEYS[keyIndex],
    )
  ) {
    throw new Error(
      `Capability ${capabilityId} reviewed Web entry ${index} must contain exactly ` +
        `${REVIEWED_ADDITIONAL_WEB_ENTRY_KEYS.join(", ")}.`,
    );
  }
}
