import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { writeValidatedArtifactSync } from './parity-judgment-ledger.mjs';
import { downgradeStructurallyInvalidSurfaces } from './parity-structural-closure.mjs';
import { validateJsonSchema } from './schema-validator.mjs';

const contractRoot = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(contractRoot, '../../../../..');
const legacyManifestPath = resolve(contractRoot, 'parity-manifest.v2.json');
const legacySchemaPath = resolve(contractRoot, 'parity-manifest.v2.schema.json');
const overridePath = resolve(contractRoot, 'parity-journey-overrides.v3.json');
const manifestPath = resolve(contractRoot, 'parity-manifest.v3.json');
const schemaPath = resolve(contractRoot, 'parity-manifest.v3.schema.json');
const check = process.argv.slice(2).includes('--check');

assertUpstreamPreflight();
const legacyManifest = readJson(legacyManifestPath);
const legacySchema = readJson(legacySchemaPath);
const overrides = indexOverrides(readJson(overridePath), legacyManifest.capabilities);
const schema = createV3Schema(legacySchema);
const manifest = downgradeStructurallyInvalidSurfaces({
  ...legacyManifest,
  $schema: './parity-manifest.v3.schema.json',
  schema_version: '3.0.0',
  capabilities: legacyManifest.capabilities.map((capability) => ({
    ...capability,
    journeys: overrides.get(capability.id) ?? [defaultJourney(capability)],
  })),
});
assertSchemaValid(schema, manifest);

const serializedSchema = `${JSON.stringify(schema, null, 2)}\n`;
const serializedManifest = `${JSON.stringify(manifest)}\n`;

if (check) {
  assertCurrent(schemaPath, serializedSchema);
  assertCurrent(manifestPath, serializedManifest);
} else {
  writeValidatedArtifactSync(schemaPath, serializedSchema);
  writeValidatedArtifactSync(manifestPath, serializedManifest);
}

console.log(
  `${check ? 'Verified' : 'Generated'} parity manifest v3 with ` +
    `${manifest.capabilities.length} capabilities and ` +
    `${manifest.capabilities.reduce((total, capability) => total + capability.journeys.length, 0)} journeys.`,
);

function readJson(path) {
  return JSON.parse(readFileSync(path, 'utf8'));
}

function assertUpstreamPreflight() {
  const checks = [
    {
      args: [],
      label: 'Web production inventory',
      path: resolve(repositoryRoot, 'web/scripts/web-route-inventory.mjs'),
    },
    {
      args: ['--check'],
      label: 'v2 production source',
      path: resolve(contractRoot, 'generate-parity-manifest-v2.mjs'),
    },
  ];
  const failures = checks.map(runUpstreamCheck).filter(Boolean);
  if (failures.length > 0) {
    throw new Error(`Parity manifest v3 upstream preflight failed:\n${failures.join('\n')}`);
  }
}

function runUpstreamCheck({ args, label, path }) {
  const result = spawnSync(process.execPath, [path, ...args], {
    cwd: repositoryRoot,
    encoding: 'utf8',
    maxBuffer: 4 * 1024 * 1024,
  });
  if (result.status === 0 && !result.error) return null;
  const detail = [result.error?.message, result.stderr, result.stdout]
    .filter((value) => typeof value === 'string' && value.trim().length > 0)
    .map((value) => value.trim())
    .join('\n');
  const termination =
    result.status === null ? `signal ${result.signal ?? 'unknown'}` : `exit ${result.status}`;
  return `${label} preflight failed (${termination})${detail ? `:\n${detail}` : '.'}`;
}

function assertSchemaValid(schema, manifest) {
  const errors = validateJsonSchema(schema, manifest);
  if (errors.length > 0) {
    throw new Error(`Parity manifest v3 schema validation failed:\n${errors.join('\n')}`);
  }
}

function assertCurrent(path, expected) {
  if (readFileSync(path, 'utf8') !== expected) {
    throw new Error(`${path} is stale; regenerate parity manifest v3.`);
  }
}

function createV3Schema(input) {
  const schema = structuredClone(input);
  schema.title = 'MemStack Desktop and Web Native Parity Manifest v3';
  schema.properties.$schema.const = './parity-manifest.v3.schema.json';
  schema.properties.schema_version.const = '3.0.0';

  const capability = schema.$defs.capability;
  capability.required.splice(capability.required.indexOf('judgment'), 0, 'journeys');
  capability.properties.journeys = {
    type: 'array',
    minItems: 1,
    items: { $ref: '#/$defs/journey' },
  };
  schema.$defs.journeyModePolicy = {
    type: 'object',
    additionalProperties: false,
    required: ['web', 'desktop_cloud', 'desktop_local', 'native_only'],
    properties: Object.fromEntries(
      ['web', 'desktop_cloud', 'desktop_local', 'native_only'].map((surface) => [
        surface,
        { enum: ['required', 'not_applicable'] },
      ]),
    ),
  };
  schema.$defs.journeyActions = {
    type: 'object',
    additionalProperties: false,
    required: ['web', 'desktop_cloud', 'desktop_local', 'native_only'],
    properties: Object.fromEntries(
      ['web', 'desktop_cloud', 'desktop_local', 'native_only'].map((surface) => [
        surface,
        {
          type: 'array',
          uniqueItems: true,
          items: { $ref: '#/$defs/identifier' },
        },
      ]),
    ),
  };
  schema.$defs.journey = {
    type: 'object',
    additionalProperties: false,
    required: [
      'id',
      'title',
      'mode_policy',
      'actions',
      'api_contracts',
      'data_states',
      'interaction_states',
      'evidence_requirements',
      'expected_observable_result',
    ],
    properties: {
      id: { $ref: '#/$defs/identifier' },
      title: { $ref: '#/$defs/nonEmptyString' },
      mode_policy: { $ref: '#/$defs/journeyModePolicy' },
      actions: { $ref: '#/$defs/journeyActions' },
      api_contracts: {
        type: 'array',
        minItems: 1,
        items: { $ref: '#/$defs/apiContract' },
      },
      data_states: extendUniqueItemEnum(capability.properties.data_states, [
        'expired',
        'answered',
        'rejected',
      ]),
      interaction_states: structuredClone(capability.properties.interaction_states),
      evidence_requirements: extendUniqueItemEnum(
        capability.properties.evidence_requirements,
        ['vault_persistence', 'native_file_dialog', 'private_control_pipe'],
      ),
      expected_observable_result: { $ref: '#/$defs/nonEmptyString' },
    },
  };
  return schema;
}

function extendUniqueItemEnum(input, additionalValues) {
  const schema = structuredClone(input);
  schema.items.enum = [...schema.items.enum, ...additionalValues];
  return schema;
}

function defaultJourney(capability) {
  return {
    id: 'primary',
    title: capability.title,
    mode_policy: mapSurfaces(capability, (surface) =>
      surface.disposition === 'not_applicable' ? 'not_applicable' : 'required',
    ),
    actions: mapSurfaces(capability, (surface) => [...surface.allowed_actions]),
    api_contracts: capability.api_contracts,
    data_states: capability.data_states,
    interaction_states: capability.interaction_states,
    evidence_requirements: capability.evidence_requirements,
    expected_observable_result: capability.expected_observable_result,
  };
}

function mapSurfaces(capability, project) {
  return Object.fromEntries(
    ['web', 'desktop_cloud', 'desktop_local', 'native_only'].map((surfaceName) => [
      surfaceName,
      project(capability.surfaces[surfaceName]),
    ]),
  );
}

function indexOverrides(catalog, capabilities) {
  if (!catalog || catalog.schema_version !== '3.0.0' || !Array.isArray(catalog.capabilities)) {
    throw new Error('Parity journey override catalog is invalid.');
  }
  const knownCapabilityIds = new Set(capabilities.map((capability) => capability.id));
  const indexed = new Map();
  for (const record of catalog.capabilities) {
    if (!knownCapabilityIds.has(record.capability_id)) {
      throw new Error(`Unknown journey override capability ${record.capability_id}.`);
    }
    if (indexed.has(record.capability_id) || !Array.isArray(record.journeys)) {
      throw new Error(`Duplicate or invalid journey override ${record.capability_id}.`);
    }
    indexed.set(
      record.capability_id,
      record.journeys.map((journey) => normalizeOverrideJourney(journey)),
    );
  }
  return indexed;
}

function normalizeOverrideJourney(journey) {
  const modePolicy = journey.mode_policy;
  const actions = journey.actions;
  const surfaceNames = ['web', 'desktop_cloud', 'desktop_local', 'native_only'];
  if (
    !journey.id ||
    !journey.title ||
    !modePolicy ||
    !actions ||
    !Array.isArray(journey.contracts) ||
    journey.contracts.length === 0 ||
    surfaceNames.some(
      (surface) =>
        !['required', 'not_applicable'].includes(modePolicy[surface]) ||
        !Array.isArray(actions[surface]),
    )
  ) {
    throw new Error(`Invalid journey override ${journey.id ?? '<unknown>'}.`);
  }
  return {
    id: journey.id,
    title: journey.title,
    mode_policy: modePolicy,
    actions,
    api_contracts: journey.contracts.flatMap(expandContract),
    data_states: journey.data_states,
    interaction_states: journey.interaction_states,
    evidence_requirements: journey.evidence_requirements,
    expected_observable_result: journey.expected_observable_result,
  };
}

function expandContract(contract) {
  return contract.surfaces.map((surface) => ({
    surface,
    method: contract.method,
    path: contract.path,
    authority: contract.method === 'IPC' ? 'electron' : authorityForSurface(surface),
  }));
}

function authorityForSurface(surface) {
  if (surface === 'web') return 'web_service';
  if (surface === 'desktop_cloud') return 'cloud_service';
  if (surface === 'desktop_local') return 'sidecar';
  return 'electron';
}
