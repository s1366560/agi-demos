import { createHash } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';

export function digestParityJudgmentInput(input) {
  return `sha256:${createHash('sha256').update(JSON.stringify(input)).digest('hex')}`;
}

export function createParityJudgmentOutput(surfaces) {
  return {
    verdict: 'accepted',
    ...Object.fromEntries(
      Object.entries(surfaces).map(([surfaceName, surface]) => [
        surfaceName,
        surfaceSummary(surface),
      ]),
    ),
  };
}

export function finalizeParityJudgmentClosure({
  beforeStructuralClosure,
  afterStructuralClosure,
  externalJudgmentCapabilityIds = [],
}) {
  if (
    beforeStructuralClosure?.schema_version !== '4.0.0' ||
    afterStructuralClosure?.schema_version !== '4.0.0'
  ) {
    throw new Error('Parity judgment closure requires v4 manifests.');
  }
  const beforeById = indexCapabilities(beforeStructuralClosure.capabilities);
  const externalCapabilityIds = new Set(externalJudgmentCapabilityIds);
  if (externalCapabilityIds.size !== externalJudgmentCapabilityIds.length) {
    throw new Error('Parity judgment closure has duplicate external capability ids.');
  }
  const finalized = structuredClone(afterStructuralClosure);

  for (const capability of finalized.capabilities ?? []) {
    const beforeCapability = beforeById.get(capability.id);
    if (!beforeCapability) {
      throw new Error(`Parity judgment closure has no pre-closure capability ${capability.id}.`);
    }
    beforeById.delete(capability.id);
    if (externalCapabilityIds.delete(capability.id)) {
      if (!isDeepStrictEqual(beforeCapability.judgment, capability.judgment)) {
        throw new Error(
          `Structural closure changed external structured Agent judgment for ${capability.id}.`,
        );
      }
      continue;
    }
    const input = {
      ...capability.judgment.input,
      surfaces: structuredClone(capability.surfaces),
    };
    capability.judgment = {
      ...capability.judgment,
      input,
      input_digest: digestParityJudgmentInput(input),
      output: createParityJudgmentOutput(capability.surfaces),
    };
  }

  if (beforeById.size > 0) {
    throw new Error(
      `Parity judgment closure lost capabilities ${[...beforeById.keys()].join(', ')}.`,
    );
  }
  if (externalCapabilityIds.size > 0) {
    throw new Error(
      `Parity judgment closure has unknown external capabilities ${[
        ...externalCapabilityIds,
      ].join(', ')}.`,
    );
  }
  assertParityJudgmentClosure(finalized);
  return finalized;
}

export function assertParityJudgmentClosure(manifest) {
  for (const capability of manifest?.capabilities ?? []) {
    const input = capability?.judgment?.input;
    if (!input || typeof input !== 'object' || Array.isArray(input)) {
      throw new Error(`Parity judgment input is invalid for ${capability?.id}.`);
    }
    if (!isDeepStrictEqual(input.surfaces, capability.surfaces)) {
      throw new Error(`Parity judgment input surfaces drifted for ${capability.id}.`);
    }
    if (capability.judgment.input_digest !== digestParityJudgmentInput(input)) {
      throw new Error(`Parity judgment input digest drifted for ${capability.id}.`);
    }
    if (
      !isDeepStrictEqual(
        capability.judgment.output,
        createParityJudgmentOutput(capability.surfaces),
      )
    ) {
      throw new Error(`Parity judgment output drifted for ${capability.id}.`);
    }
  }
}

function indexCapabilities(capabilities) {
  const indexed = new Map();
  for (const capability of capabilities ?? []) {
    if (!capability?.id || indexed.has(capability.id)) {
      throw new Error(
        `Parity judgment closure has duplicate or invalid capability ${capability?.id}.`,
      );
    }
    indexed.set(capability.id, capability);
  }
  return indexed;
}

function surfaceSummary(surface) {
  return {
    disposition: surface.disposition,
    implementation_status: surface.implementation_status,
    availability: surface.availability,
    reason_code: surface.reason_code,
    authority: surface.authority,
    supporting_authorities: [...surface.supporting_authorities],
  };
}
