const SURFACE_NAMES = Object.freeze([
  'web',
  'desktop_cloud',
  'desktop_local',
  'native_only',
]);
const ACTIVE_AVAILABILITIES = new Set(['available', 'degraded']);
const REASON_CODE_PATTERN = /^[a-z0-9]+(?:_[a-z0-9]+)*$/u;
const ACTION_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/u;
const UNAVAILABLE_CONTRACT_PREFIXES = Object.freeze(['planned:', 'unavailable:']);

export function validateParityStructuralClosure(manifest) {
  const issues = [];
  for (const capability of manifest?.capabilities ?? []) {
    validateCapability(capability, issues);
  }
  return Object.freeze(issues.map((issue) => Object.freeze(issue)));
}

export function assertParityStructuralClosure(manifest) {
  const issues = validateParityStructuralClosure(manifest);
  if (issues.length === 0) return;
  const details = issues
    .map((issue) => {
      const location = [issue.capabilityId, issue.journeyId, issue.surfaceName]
        .filter(Boolean)
        .join('.');
      return `${location}: ${issue.code}`;
    })
    .join('\n');
  throw new Error(`Parity structural closure failed:\n${details}`);
}

export function downgradeStructurallyInvalidSurfaces(manifest) {
  const normalized = structuredClone(manifest);
  const issues = validateParityStructuralClosure(normalized);
  const issueBySurface = new Map();
  for (const issue of issues) {
    if (!issue.capabilityId || !issue.surfaceName) continue;
    const capability = arrayValue(normalized.capabilities).find(
      ({ id }) => id === issue.capabilityId,
    );
    const surface = capability?.surfaces?.[issue.surfaceName];
    if (!surface || !ACTIVE_AVAILABILITIES.has(surface.availability)) continue;
    const key = `${issue.capabilityId}\0${issue.surfaceName}`;
    const current = issueBySurface.get(key);
    if (!current || compareDowngradeIssues(issue, current) < 0) {
      issueBySurface.set(key, issue);
    }
  }
  for (const issue of issueBySurface.values()) {
    const capability = normalized.capabilities.find(
      ({ id }) => id === issue.capabilityId,
    );
    const surface = capability.surfaces[issue.surfaceName];
    capability.surfaces[issue.surfaceName] = {
      ...surface,
      implementation_status: 'unavailable',
      availability: 'unavailable',
      reason_code: `parity_structural_${issue.code}`,
      allowed_actions: [],
    };
  }
  return normalized;
}

function compareDowngradeIssues(left, right) {
  const priority = (issue) =>
    issue.code.startsWith('active_surface_')
      ? 0
      : issue.code.startsWith('active_journey_')
        ? 1
        : 2;
  return priority(left) - priority(right) || left.code.localeCompare(right.code);
}

function validateCapability(capability, issues) {
  const capabilityId = stringValue(capability?.id, '<unknown-capability>');
  const apiContracts = arrayValue(capability?.api_contracts);

  for (const surfaceName of SURFACE_NAMES) {
    const surface = capability?.surfaces?.[surfaceName];
    validateSurface({
      capabilityId,
      surface,
      surfaceName,
      contracts: contractsForSurface(apiContracts, surfaceName),
      issues,
    });
  }

  for (const journey of arrayValue(capability?.journeys)) {
    validateJourney({ capabilityId, capability, journey, issues });
  }
}

function validateSurface({
  capabilityId,
  surface,
  surfaceName,
  contracts,
  issues,
}) {
  if (!surface || typeof surface !== 'object' || Array.isArray(surface)) {
    pushIssue(issues, {
      code: 'surface_contract_missing',
      capabilityId,
      surfaceName,
    });
    return;
  }

  const availability = surface.availability;
  const active = ACTIVE_AVAILABILITIES.has(availability);
  validateReasonCode({ capabilityId, surface, surfaceName, active, issues });
  validateAvailabilityPair({ capabilityId, surface, surfaceName, issues });

  if (!active) return;
  if (!validActions(surface.allowed_actions)) {
    pushIssue(issues, {
      code: 'active_surface_actions_missing',
      capabilityId,
      surfaceName,
    });
  }
  validateActiveContracts({
    capabilityId,
    surface,
    surfaceName,
    contracts,
    issues,
    issuePrefix: 'active_surface',
  });
}

function validateJourney({ capabilityId, capability, journey, issues }) {
  const journeyId = stringValue(journey?.id, '<unknown-journey>');
  for (const surfaceName of SURFACE_NAMES) {
    const policy = journey?.mode_policy?.[surfaceName];
    const actions = journey?.actions?.[surfaceName];
    if (policy === 'not_applicable') {
      if (arrayValue(actions).length > 0) {
        pushIssue(issues, {
          code: 'not_applicable_journey_actions_present',
          capabilityId,
          journeyId,
          surfaceName,
        });
      }
      continue;
    }
    const surface = capability?.surfaces?.[surfaceName];
    if (policy !== 'required' || !ACTIVE_AVAILABILITIES.has(surface?.availability)) {
      continue;
    }
    if (!validActions(actions)) {
      pushIssue(issues, {
        code: 'active_journey_actions_missing',
        capabilityId,
        journeyId,
        surfaceName,
      });
    }
    validateActiveContracts({
      capabilityId,
      journeyId,
      surface,
      surfaceName,
      contracts: contractsForSurface(journey?.api_contracts, surfaceName),
      issues,
      issuePrefix: 'active_journey',
    });
  }
}

function validateReasonCode({ capabilityId, surface, surfaceName, active, issues }) {
  const reasonCode = surface.reason_code;
  if (reasonCode !== null && !validReasonCode(reasonCode)) {
    pushIssue(issues, {
      code: 'surface_reason_code_invalid',
      capabilityId,
      surfaceName,
    });
  }
  if (surface.availability === 'available' && reasonCode !== null) {
    pushIssue(issues, {
      code: 'available_surface_reason_code_present',
      capabilityId,
      surfaceName,
    });
    return;
  }
  if (surface.availability === 'degraded' && !validReasonCode(reasonCode)) {
    pushIssue(issues, {
      code: 'degraded_surface_reason_code_missing',
      capabilityId,
      surfaceName,
    });
    return;
  }
  if (!active && !validReasonCode(reasonCode)) {
    pushIssue(issues, {
      code: 'inactive_surface_reason_code_missing',
      capabilityId,
      surfaceName,
    });
  }
}

function validateAvailabilityPair({ capabilityId, surface, surfaceName, issues }) {
  const validStatuses = {
    available: new Set(['implemented']),
    degraded: new Set(['partial']),
    unavailable: new Set(['missing', 'partial', 'unavailable']),
    not_applicable: new Set(['not_applicable']),
  };
  if (!validStatuses[surface.availability]?.has(surface.implementation_status)) {
    pushIssue(issues, {
      code: 'surface_status_availability_mismatch',
      capabilityId,
      surfaceName,
    });
  }
}

function validateActiveContracts({
  capabilityId,
  journeyId,
  surface,
  surfaceName,
  contracts,
  issues,
  issuePrefix,
}) {
  if (contracts.length === 0) {
    pushIssue(issues, {
      code: `${issuePrefix}_api_contract_missing`,
      capabilityId,
      journeyId,
      surfaceName,
    });
    return;
  }
  if (contracts.some(isUnavailableDeclaration)) {
    pushIssue(issues, {
      code: `${issuePrefix}_api_contract_unavailable`,
      capabilityId,
      journeyId,
      surfaceName,
    });
    return;
  }
  if (
    (surfaceName === 'web' || surface.authority === 'none') &&
    contracts.every(isExplicitNoServiceContract)
  ) {
    return;
  }
  if (!contracts.every((contract) => isModeMatchedAuthorityContract(contract, surface))) {
    pushIssue(issues, {
      code: `${issuePrefix}_api_authority_mismatch`,
      capabilityId,
      journeyId,
      surfaceName,
    });
  }
}

function isUnavailableDeclaration(contract) {
  return (
    contract?.method === 'NONE' &&
    typeof contract.path === 'string' &&
    UNAVAILABLE_CONTRACT_PREFIXES.some((prefix) => contract.path.startsWith(prefix))
  );
}

function isExplicitNoServiceContract(contract) {
  return (
    contract?.method === 'NONE' &&
    contract.authority === 'none' &&
    typeof contract.path === 'string' &&
    contract.path.startsWith('not_applicable:')
  );
}

function isModeMatchedAuthorityContract(contract, surface) {
  if (!contract || contract.authority !== surface.authority || contract.authority === 'none') {
    return false;
  }
  if (contract.method !== 'NONE') return true;
  return typeof contract.path === 'string' && contract.path.startsWith('native:');
}

function contractsForSurface(contracts, surfaceName) {
  return arrayValue(contracts).filter((contract) => contract?.surface === surfaceName);
}

function validActions(actions) {
  if (!Array.isArray(actions) || actions.length === 0) return false;
  const unique = new Set(actions);
  return unique.size === actions.length && actions.every(validAction);
}

function validAction(action) {
  return typeof action === 'string' && ACTION_PATTERN.test(action);
}

function validReasonCode(reasonCode) {
  return typeof reasonCode === 'string' && REASON_CODE_PATTERN.test(reasonCode);
}

function arrayValue(value) {
  return Array.isArray(value) ? value : [];
}

function stringValue(value, fallback) {
  return typeof value === 'string' && value.length > 0 ? value : fallback;
}

function pushIssue(issues, issue) {
  issues.push(issue);
}
