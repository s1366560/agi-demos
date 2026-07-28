export type CapabilityVersionReasonCode =
  | 'capability_contract_version_missing'
  | 'capability_contract_version_invalid'
  | 'capability_contract_version_too_old'
  | 'capability_contract_version_unsupported';

export type CapabilityContractNegotiation = {
  compatible: boolean;
  reason_code: CapabilityVersionReasonCode | null;
  service_version: string | null;
  contract_version: string | null;
  minimum_contract_version: string;
};

type ParsedSemanticVersion = {
  major: number;
  minor: number;
  patch: number;
  prerelease: string | null;
};

const SEMANTIC_VERSION_PATTERN =
  /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$/;

export function negotiateCapabilityContract(
  input: unknown,
  minimumContractVersion: string,
): CapabilityContractNegotiation {
  const minimum = parseSemanticVersion(minimumContractVersion);
  if (!minimum) {
    return incompatible(
      'capability_contract_version_invalid',
      null,
      null,
      minimumContractVersion,
    );
  }

  if (!isRecord(input)) {
    return incompatible(
      'capability_contract_version_missing',
      null,
      null,
      minimumContractVersion,
    );
  }

  const serviceVersion =
    typeof input.service_version === 'string' && isCapabilityVersion(input.service_version)
      ? input.service_version
      : null;
  const contractVersion =
    typeof input.contract_version === 'string' && isCapabilityVersion(input.contract_version)
      ? input.contract_version
      : null;
  if (input.service_version == null || input.contract_version == null) {
    return incompatible(
      'capability_contract_version_missing',
      serviceVersion,
      contractVersion,
      minimumContractVersion,
    );
  }
  if (!serviceVersion || !contractVersion) {
    return incompatible(
      'capability_contract_version_invalid',
      serviceVersion,
      contractVersion,
      minimumContractVersion,
    );
  }

  const offered = parseSemanticVersion(contractVersion)!;
  if (offered.major !== minimum.major) {
    return incompatible(
      offered.major < minimum.major
        ? 'capability_contract_version_too_old'
        : 'capability_contract_version_unsupported',
      serviceVersion,
      contractVersion,
      minimumContractVersion,
    );
  }
  if (compareSemanticVersions(offered, minimum) < 0) {
    return incompatible(
      'capability_contract_version_too_old',
      serviceVersion,
      contractVersion,
      minimumContractVersion,
    );
  }
  return {
    compatible: true,
    reason_code: null,
    service_version: serviceVersion,
    contract_version: contractVersion,
    minimum_contract_version: minimumContractVersion,
  };
}

export function isCapabilityVersion(input: unknown): input is string {
  return typeof input === 'string' && parseSemanticVersion(input) !== null;
}

function incompatible(
  reasonCode: CapabilityVersionReasonCode,
  serviceVersion: string | null,
  contractVersion: string | null,
  minimumContractVersion: string,
): CapabilityContractNegotiation {
  return {
    compatible: false,
    reason_code: reasonCode,
    service_version: serviceVersion,
    contract_version: contractVersion,
    minimum_contract_version: minimumContractVersion,
  };
}

function parseSemanticVersion(input: string): ParsedSemanticVersion | null {
  const match = SEMANTIC_VERSION_PATTERN.exec(input);
  if (!match) return null;
  return {
    major: Number(match[1]),
    minor: Number(match[2]),
    patch: Number(match[3]),
    prerelease: match[4] ?? null,
  };
}

function compareSemanticVersions(
  left: ParsedSemanticVersion,
  right: ParsedSemanticVersion,
): number {
  for (const key of ['major', 'minor', 'patch'] as const) {
    if (left[key] !== right[key]) return left[key] - right[key];
  }
  if (left.prerelease === right.prerelease) return 0;
  if (left.prerelease === null) return 1;
  if (right.prerelease === null) return -1;
  return left.prerelease.localeCompare(right.prerelease);
}

function isRecord(input: unknown): input is Record<string, unknown> {
  return typeof input === 'object' && input !== null && !Array.isArray(input);
}
