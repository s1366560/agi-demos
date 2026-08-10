import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { writeValidatedArtifactSync } from './parity-judgment-ledger.mjs';
import {
  assertParityStructuralClosure,
  downgradeStructurallyInvalidSurfaces,
} from './parity-structural-closure.mjs';
import { validateJsonSchema } from './schema-validator.mjs';

const contractRoot = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(contractRoot, '../../../../..');
const v2ManifestPath = resolve(contractRoot, 'parity-manifest.v2.json');
const v3ManifestPath = resolve(contractRoot, 'parity-manifest.v3.json');
const v3SchemaPath = resolve(contractRoot, 'parity-manifest.v3.schema.json');
const overridePath = resolve(contractRoot, 'parity-authority-overrides.v4.json');
const manifestPath = resolve(contractRoot, 'parity-manifest.v4.json');
const schemaPath = resolve(contractRoot, 'parity-manifest.v4.schema.json');
const check = process.argv.slice(2).includes('--check');
const surfaceNames = ['web', 'desktop_cloud', 'local_online', 'local_offline', 'native_only'];
const browserCapabilityId = 'browser-integration-browser-bridge';

const v2Manifest = readJson(v2ManifestPath);
const v3Manifest = readJson(v3ManifestPath);
const v3Schema = readJson(v3SchemaPath);
assertHistoricalInputs(v2Manifest, v3Manifest, v3Schema);
const v2Capabilities = indexCapabilities(v2Manifest.capabilities);
const overrides = indexAuthorityOverrides(readJson(overridePath));
const schema = createV4Schema(v3Schema);
const matchedOverrides = new Set();
const enrichedCapabilities = v3Manifest.capabilities.map((capability) =>
  projectCapability({
    capability,
    matchedOverrides,
    overrides,
    v2Capability: v2Capabilities.get(capability.id),
  }),
);
assertAllOverridesMatched(overrides, matchedOverrides);
const sourceRevision = resolveGitRevision('HEAD');
const browserCapability = createBrowserBridgeCapability(sourceRevision);
const manifest = downgradeStructurallyInvalidSurfaces({
  ...v3Manifest,
  $schema: './parity-manifest.v4.schema.json',
  schema_version: '4.0.0',
  references: {
    ...v3Manifest.references,
    audit_revision: sourceRevision,
    desktop_revision: sourceRevision,
  },
  capabilities: [...enrichedCapabilities, browserCapability],
});
assertSchemaValid(schema, manifest);
assertParityStructuralClosure(manifest);
assertNoLegacySurfaceIdentifier(schema, 'schema');
assertNoLegacySurfaceIdentifier(manifest, 'manifest');

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
  `${check ? 'Verified' : 'Generated'} parity manifest v4 with ` +
    `${manifest.capabilities.length} capabilities, ` +
    `${manifest.capabilities.reduce((total, capability) => total + capability.journeys.length, 0)} journeys, and ` +
    `${overrides.size} explicit authority overrides.`,
);

function readJson(path) {
  return JSON.parse(readFileSync(path, 'utf8'));
}

function assertHistoricalInputs(v2, v3, schema) {
  const schemaErrors = validateJsonSchema(schema, v3);
  if (schemaErrors.length > 0) {
    throw new Error(`Parity manifest v4 v3 artifact preflight failed:\n${schemaErrors.join('\n')}`);
  }
  assertParityStructuralClosure(v3);
  if (v2?.schema_version !== '2.0.0' || v3?.schema_version !== '3.0.0') {
    throw new Error('Parity manifest v4 requires historical manifest v2 and v3 inputs.');
  }
}

function indexCapabilities(capabilities) {
  const indexed = new Map();
  for (const capability of capabilities ?? []) {
    if (!capability?.id || indexed.has(capability.id)) {
      throw new Error(`Parity manifest v4 has duplicate or invalid capability ${capability?.id}.`);
    }
    indexed.set(capability.id, capability);
  }
  return indexed;
}

function projectCapability({ capability, matchedOverrides, overrides, v2Capability }) {
  if (!v2Capability) {
    throw new Error(`Parity manifest v4 has no v2 capability ${capability.id}.`);
  }
  const localPolicy = capability.judgment?.input?.local_policy;
  const apiContracts = projectContracts({
    capabilityId: capability.id,
    contracts: capability.api_contracts,
    journeyId: null,
    localPolicy,
    matchedOverrides,
    overrides,
  });
  const journeys = capability.journeys.map((journey) => ({
    ...journey,
    mode_policy: projectSurfaceRecord(journey.mode_policy, localPolicy),
    actions: projectSurfaceRecord(journey.actions, localPolicy),
    api_contracts: projectContracts({
      capabilityId: capability.id,
      contracts: journey.api_contracts,
      journeyId: journey.id,
      localPolicy,
      matchedOverrides,
      overrides,
    }),
  }));
  const supportingBySurface = supportingAuthoritiesBySurface(apiContracts, journeys);
  const surfaces = Object.fromEntries(
    surfaceNames.map((surfaceName) => {
      const sourceSurface = sourceSurfaceFor(surfaceName, localPolicy);
      return [
        surfaceName,
        {
          ...v2Capability.surfaces[sourceSurface],
          supporting_authorities: supportingBySurface.get(surfaceName) ?? [],
        },
      ];
    }),
  );
  const productionEntries = projectSurfaceRecord(capability.production_entries, localPolicy);
  const permissionRequirements = projectSurfaceRows(
    capability.permission_requirements,
    localPolicy,
  );
  return {
    ...capability,
    production_entries: productionEntries,
    api_contracts: apiContracts,
    permission_requirements: permissionRequirements,
    surfaces,
    judgment: projectJudgment({
      capability,
      journeys,
      localPolicy,
      permissionRequirements,
      productionEntries,
      surfaces,
      apiContracts,
    }),
    journeys,
  };
}

function projectSurfaceRecord(record, localPolicy) {
  return Object.fromEntries(
    surfaceNames.map((surfaceName) => [
      surfaceName,
      structuredClone(record[sourceSurfaceFor(surfaceName, localPolicy)]),
    ]),
  );
}

function projectSurfaceRows(rows, localPolicy) {
  return surfaceNames.flatMap((surfaceName) => {
    const sourceSurface = sourceSurfaceFor(surfaceName, localPolicy);
    return rows
      .filter((row) => row.surface === sourceSurface)
      .map((row) => ({ ...row, surface: surfaceName }));
  });
}

function projectContracts({
  capabilityId,
  contracts,
  journeyId,
  localPolicy,
  matchedOverrides,
  overrides,
}) {
  return surfaceNames.flatMap((surfaceName) => {
    const sourceSurface = sourceSurfaceFor(surfaceName, localPolicy);
    return contracts
      .filter((contract) => contract.surface === sourceSurface)
      .map((contract) => {
        const projected = { ...contract, surface: surfaceName };
        const key = authorityOverrideKey({
          capability_id: capabilityId,
          journey_id: journeyId,
          ...projected,
        });
        const override = overrides.get(key);
        if (override) matchedOverrides.add(key);
        return {
          ...projected,
          authority: override?.authority ?? projected.authority,
          authority_role: override?.authority_role ?? 'primary',
        };
      });
  });
}

function sourceSurfaceFor(surfaceName, localPolicy) {
  if (surfaceName === 'local_online') {
    return localPolicy === 'cloud_only' ? 'desktop_cloud' : 'desktop_local';
  }
  if (surfaceName === 'local_offline') return 'desktop_local';
  return surfaceName;
}

function projectJudgment({
  apiContracts,
  capability,
  journeys,
  localPolicy,
  permissionRequirements,
  productionEntries,
  surfaces,
}) {
  const input = {
    ...capability.judgment.input,
    production_entries: productionEntries,
    api_contracts: apiContracts,
    permission_requirements: permissionRequirements,
    surfaces,
    journeys,
  };
  const output = {
    verdict: 'accepted',
    ...Object.fromEntries(
      surfaceNames.map((surfaceName) => [surfaceName, surfaceSummary(surfaces[surfaceName])]),
    ),
  };
  return {
    ...capability.judgment,
    input,
    input_digest: digestInput(input),
    output,
    rationale:
      `${capability.judgment.rationale} Manifest v4 projects local_online and ` +
      `local_offline from the accepted ${localPolicy} policy and records compound authority roles ` +
      'without mutating the historical v2/v3 judgment.',
  };
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

function digestInput(input) {
  return `sha256:${createHash('sha256').update(JSON.stringify(input)).digest('hex')}`;
}

function indexAuthorityOverrides(catalog) {
  if (!catalog || catalog.schema_version !== '4.0.0' || !Array.isArray(catalog.contracts)) {
    throw new Error('Parity authority override catalog is invalid.');
  }
  const indexed = new Map();
  for (const override of catalog.contracts) {
    if (!validAuthorityOverride(override)) {
      throw new Error('Parity authority override catalog contains an invalid record.');
    }
    const key = authorityOverrideKey(override);
    if (indexed.has(key)) throw new Error(`Duplicate authority override ${key}.`);
    indexed.set(key, override);
  }
  return indexed;
}

function validAuthorityOverride(override) {
  return (
    override &&
    typeof override.capability_id === 'string' &&
    (override.journey_id === null || typeof override.journey_id === 'string') &&
    surfaceNames.includes(override.surface) &&
    typeof override.method === 'string' &&
    typeof override.path === 'string' &&
    typeof override.authority === 'string' &&
    ['primary', 'supporting'].includes(override.authority_role)
  );
}

function authorityOverrideKey(record) {
  return [
    record.capability_id,
    record.journey_id ?? '<capability>',
    record.surface,
    record.method,
    record.path,
  ].join('\0');
}

function assertAllOverridesMatched(overrides, matchedOverrides) {
  for (const key of overrides.keys()) {
    if (!matchedOverrides.has(key)) {
      throw new Error(`Authority override ${key} did not match a v3 contract.`);
    }
  }
}

function supportingAuthoritiesBySurface(apiContracts, journeys) {
  const supporting = new Map(surfaceNames.map((surfaceName) => [surfaceName, new Set()]));
  for (const contract of [
    ...apiContracts,
    ...journeys.flatMap((journey) => journey.api_contracts),
  ]) {
    if (contract.authority_role === 'supporting') {
      supporting.get(contract.surface)?.add(contract.authority);
    }
  }
  return new Map(
    [...supporting.entries()].map(([surfaceName, authorities]) => [
      surfaceName,
      [...authorities].sort(),
    ]),
  );
}

function createBrowserBridgeCapability(sourceRevision) {
  const sourcePaths = [
    'agi-stack/apps/browser-extension/entrypoints/background.ts',
    'agi-stack/apps/browser-extension/src/handlers.ts',
    'agi-stack/apps/browser-extension/src/protocol.ts',
    'agi-stack/crates/adapters-browser/src/lib.rs',
    'agi-stack/apps/desktop/sidecar/src/local_runtime/browser_bridge.rs',
    'agi-stack/apps/desktop/sidecar/src/native_host.rs',
    'agi-stack/apps/desktop/src/features/settings/BrowserIntegrationSettingsPage.tsx',
  ];
  const boundEntries = sourcePaths.map((path) => bindSourceEntry(path, sourceRevision));
  const notApplicable = (reasonCode) => ({
    disposition: 'not_applicable',
    implementation_status: 'not_applicable',
    availability: 'not_applicable',
    reason_code: reasonCode,
    authority: 'none',
    supporting_authorities: [],
    allowed_actions: [],
    intentional_deviation:
      'Browser Bridge is an isolated native-only capability and is not counted as ordinary Web or Desktop route parity.',
  });
  const nativeSurface = {
    disposition: 'native_only',
    implementation_status: 'partial',
    availability: 'degraded',
    reason_code: 'browser_bridge_release_and_registration_evidence_incomplete',
    authority: 'sidecar',
    supporting_authorities: ['browser_extension', 'electron'],
    allowed_actions: [
      'manage-origin-consent',
      'list-tabs',
      'snapshot-page',
      'capture-screenshot',
      'navigate',
      'click',
      'type',
    ],
    intentional_deviation: null,
  };
  const surfaces = {
    web: notApplicable('native_surface_not_available_on_web'),
    desktop_cloud: notApplicable('browser_bridge_native_only'),
    local_online: notApplicable('browser_bridge_native_only'),
    local_offline: notApplicable('browser_bridge_native_only'),
    native_only: nativeSurface,
  };
  const apiContracts = [
    ...surfaceNames
      .filter((surface) => surface !== 'native_only')
      .map((surface) => ({
        surface,
        method: 'NONE',
        path: `not_applicable:native-only/${browserCapabilityId}`,
        authority: 'none',
        authority_role: 'primary',
      })),
    {
      surface: 'native_only',
      method: 'IPC',
      path: 'sidecar://browser-bridge',
      authority: 'sidecar',
      authority_role: 'primary',
    },
    {
      surface: 'native_only',
      method: 'IPC',
      path: 'browser-extension://native-messaging',
      authority: 'browser_extension',
      authority_role: 'supporting',
    },
    {
      surface: 'native_only',
      method: 'IPC',
      path: 'electron://settings/browser-integration',
      authority: 'electron',
      authority_role: 'supporting',
    },
  ];
  const modePolicy = Object.fromEntries(
    surfaceNames.map((surface) => [
      surface,
      surface === 'native_only' ? 'required' : 'not_applicable',
    ]),
  );
  const actions = Object.fromEntries(
    surfaceNames.map((surface) => [
      surface,
      surface === 'native_only' ? [...nativeSurface.allowed_actions] : [],
    ]),
  );
  const productionEntries = {
    web: [`not_applicable:web/${browserCapabilityId}`],
    desktop_cloud: boundEntries,
    local_online: boundEntries,
    local_offline: boundEntries,
    native_only: boundEntries,
  };
  const input = {
    capability_id: browserCapabilityId,
    kind: 'native_only',
    title: 'Browser Integration Bridge',
    scope: ['global'],
    production_entries: productionEntries,
    api_contracts: apiContracts,
    surfaces,
    evidence_requirements: [
      'contract',
      'native_electron',
      'sidecar_authority',
      'desktop_bundle',
      'release_pipeline',
      'browser_extension',
    ],
    local_policy: 'native_only',
    audited_revision: sourceRevision,
  };
  return {
    id: browserCapabilityId,
    title: 'Browser Integration Bridge',
    domain: 'native-browser',
    scope: ['global'],
    source_revision: sourceRevision,
    web_route_ids: [],
    web_route_registration_ids: [],
    web_production_dependencies: [],
    audited_web_sources: [],
    production_entries: productionEntries,
    api_contracts: apiContracts,
    required_permissions: ['native-shell', 'browser-origin-consent'],
    route_entry_permissions: [],
    permission_requirements: [
      {
        surface: 'native_only',
        actions: [...nativeSurface.allowed_actions],
        authentication: 'native_shell',
        authorization: ['browser-origin-consent'],
        enforcement: 'enforced',
        feature_gate: 'browser_bridge_registered',
      },
    ],
    data_states: ['loading', 'ready', 'forbidden', 'unavailable', 'retry'],
    interaction_states: [
      'register',
      'connect',
      'request-origin-consent',
      'invoke',
      'disconnect',
      'retry',
    ],
    expected_observable_result:
      'The native browser bridge exposes only consented browser origins through the sidecar authority, an authenticated native-messaging extension transport, and the allowlisted Electron settings surface.',
    surfaces,
    evidence_requirements: input.evidence_requirements,
    judgment: {
      agent_id: '/root',
      tool_name: 'structured_parity_judgment',
      input,
      input_digest: digestInput(input),
      output: {
        verdict: 'accepted',
        ...Object.fromEntries(
          surfaceNames.map((surface) => [surface, surfaceSummary(surfaces[surface])]),
        ),
      },
      rationale:
        'Browser Bridge is a separate native-only failure domain. Sidecar owns the decision authority; the browser extension and Electron settings UI are supporting transports. Release packaging and native-host registration evidence remain incomplete.',
      latency_ms: 1,
      recorded_at: '2026-08-10T09:05:37+08:00',
    },
    journeys: [
      {
        id: 'primary',
        title: 'Browser Integration Bridge',
        mode_policy: modePolicy,
        actions,
        api_contracts: apiContracts,
        data_states: ['loading', 'ready', 'forbidden', 'unavailable', 'retry'],
        interaction_states: [
          'register',
          'connect',
          'request-origin-consent',
          'invoke',
          'disconnect',
          'retry',
        ],
        evidence_requirements: input.evidence_requirements,
        expected_observable_result:
          'Only the native-only surface may activate Browser Bridge, and it remains degraded until release registration and packaged native-host evidence are current.',
      },
    ],
  };
}

function bindSourceEntry(path, sourceRevision) {
  const liveBytes = readFileSync(resolve(repositoryRoot, path));
  const revisionBytes = execFileSync('git', ['show', `${sourceRevision}:${path}`], {
    cwd: repositoryRoot,
    maxBuffer: 32 * 1024 * 1024,
  });
  if (!liveBytes.equals(revisionBytes)) {
    throw new Error(`Browser Bridge production entry ${path} differs from ${sourceRevision}.`);
  }
  return {
    entry_type: 'source',
    path,
    sha256: `sha256:${createHash('sha256').update(liveBytes).digest('hex')}`,
    declaration: null,
  };
}

function resolveGitRevision(revision) {
  return execFileSync('git', ['rev-parse', '--verify', `${revision}^{commit}`], {
    cwd: repositoryRoot,
    encoding: 'utf8',
  }).trim();
}

function createV4Schema(input) {
  const schema = structuredClone(input);
  schema.title = 'MemStack Desktop and Web Native Parity Manifest v4';
  schema.properties.$schema.const = './parity-manifest.v4.schema.json';
  schema.properties.schema_version.const = '4.0.0';

  const authorities = [
    'web_service',
    'cloud_service',
    'sidecar',
    'electron',
    'browser_extension',
    'none',
  ];
  const surface = schema.$defs.surface;
  surface.required.splice(surface.required.indexOf('allowed_actions'), 0, 'supporting_authorities');
  surface.properties.authority.enum = authorities;
  surface.properties.supporting_authorities = {
    type: 'array',
    uniqueItems: true,
    items: { enum: authorities.filter((authority) => authority !== 'none') },
  };
  schema.$defs.surfaceSummary.required.push('supporting_authorities');
  schema.$defs.surfaceSummary.properties.authority.enum = authorities;
  schema.$defs.surfaceSummary.properties.supporting_authorities = structuredClone(
    surface.properties.supporting_authorities,
  );

  replaceSurfaceMap(schema.$defs.productionEntries, (surfaceName) =>
    surfaceName === 'web'
      ? {
          type: 'array',
          minItems: 1,
          items: { $ref: '#/$defs/nonEmptyString' },
        }
      : {
          type: 'array',
          minItems: 1,
          items: { $ref: '#/$defs/productionEntry' },
        },
  );
  replaceSurfaceMap(schema.$defs.capability.properties.surfaces, () => ({
    $ref: '#/$defs/surface',
  }));
  replaceSurfaceMap(schema.$defs.journeyModePolicy, () => ({
    enum: ['required', 'not_applicable'],
  }));
  replaceSurfaceMap(schema.$defs.journeyActions, () => ({
    type: 'array',
    uniqueItems: true,
    items: { $ref: '#/$defs/identifier' },
  }));
  const judgmentOutput = schema.$defs.judgment.properties.output;
  judgmentOutput.required = ['verdict', ...surfaceNames];
  judgmentOutput.properties = {
    verdict: { const: 'accepted' },
    ...Object.fromEntries(
      surfaceNames.map((surfaceName) => [surfaceName, { $ref: '#/$defs/surfaceSummary' }]),
    ),
  };

  const apiContract = schema.$defs.apiContract;
  apiContract.required.push('authority_role');
  apiContract.properties.surface.enum = surfaceNames;
  apiContract.properties.authority.enum = authorities;
  apiContract.properties.authority_role = { enum: ['primary', 'supporting'] };
  schema.$defs.permissionRequirement.properties.surface.enum = surfaceNames;
  schema.$defs.authorizationPredicate.enum.push('browser-origin-consent');
  for (const evidenceSchema of [
    schema.$defs.capability.properties.evidence_requirements,
    schema.$defs.journey.properties.evidence_requirements,
  ]) {
    if (!evidenceSchema.items.enum.includes('browser_extension')) {
      evidenceSchema.items.enum.push('browser_extension');
    }
  }
  return schema;
}

function replaceSurfaceMap(schema, propertyForSurface) {
  schema.required = [...surfaceNames];
  schema.properties = Object.fromEntries(
    surfaceNames.map((surfaceName) => [surfaceName, propertyForSurface(surfaceName)]),
  );
}

function assertSchemaValid(schema, manifest) {
  const errors = validateJsonSchema(schema, manifest);
  if (errors.length > 0) {
    throw new Error(`Parity manifest v4 schema validation failed:\n${errors.join('\n')}`);
  }
}

function assertNoLegacySurfaceIdentifier(value, label) {
  if (containsLegacySurfaceIdentifier(value)) {
    throw new Error(`Parity manifest v4 ${label} contains desktop_local.`);
  }
}

function containsLegacySurfaceIdentifier(value) {
  if (value === 'desktop_local') return true;
  if (Array.isArray(value)) return value.some(containsLegacySurfaceIdentifier);
  if (!value || typeof value !== 'object') return false;
  return Object.entries(value).some(
    ([key, nested]) => key === 'desktop_local' || containsLegacySurfaceIdentifier(nested),
  );
}

function assertCurrent(path, expected) {
  if (readFileSync(path, 'utf8') !== expected) {
    throw new Error(`${path} is stale; regenerate parity manifest v4.`);
  }
}
