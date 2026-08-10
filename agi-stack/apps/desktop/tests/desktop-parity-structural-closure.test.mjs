import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

import {
  assertParityStructuralClosure,
  downgradeStructurallyInvalidSurfaces,
  validateParityStructuralClosure,
} from '../contracts/desktop-web-parity/parity-structural-closure.mjs';

const contractRoot = new URL('../contracts/desktop-web-parity/', import.meta.url);
const surfaces = ['web', 'desktop_cloud', 'desktop_local', 'native_only'];

function surface(overrides = {}) {
  return {
    disposition: 'native_equivalent',
    implementation_status: 'implemented',
    availability: 'available',
    reason_code: null,
    authority: 'cloud_service',
    allowed_actions: ['view'],
    intentional_deviation: null,
    ...overrides,
  };
}

function contract(overrides = {}) {
  return {
    surface: 'desktop_cloud',
    method: 'GET',
    path: '/api/v1/resources/',
    authority: 'cloud_service',
    ...overrides,
  };
}

function capability(overrides = {}) {
  const desktopCloud = surface();
  return {
    id: 'test-capability',
    kind: 'canonical',
    surfaces: {
      web: surface({
        disposition: 'not_applicable',
        implementation_status: 'not_applicable',
        availability: 'not_applicable',
        reason_code: 'test_web_not_applicable',
        authority: 'none',
        allowed_actions: [],
      }),
      desktop_cloud: desktopCloud,
      desktop_local: surface({
        implementation_status: 'missing',
        availability: 'unavailable',
        reason_code: 'test_local_unavailable',
        authority: 'none',
        allowed_actions: [],
      }),
      native_only: surface({
        disposition: 'not_applicable',
        implementation_status: 'not_applicable',
        availability: 'not_applicable',
        reason_code: 'test_native_not_applicable',
        authority: 'none',
        allowed_actions: [],
      }),
    },
    api_contracts: [
      contract({
        surface: 'web',
        method: 'NONE',
        path: 'not_applicable:test_web_not_applicable',
        authority: 'none',
      }),
      contract(),
      contract({
        surface: 'desktop_local',
        method: 'NONE',
        path: 'not_applicable:test_local_unavailable',
        authority: 'none',
      }),
      contract({
        surface: 'native_only',
        method: 'NONE',
        path: 'not_applicable:test_native_not_applicable',
        authority: 'none',
      }),
    ],
    journeys: [
      {
        id: 'primary',
        mode_policy: {
          web: 'not_applicable',
          desktop_cloud: 'required',
          desktop_local: 'required',
          native_only: 'not_applicable',
        },
        actions: {
          web: [],
          desktop_cloud: [...desktopCloud.allowed_actions],
          desktop_local: ['view'],
          native_only: [],
        },
        api_contracts: [contract()],
      },
    ],
    ...overrides,
  };
}

function manifest(candidate = capability()) {
  return { schema_version: '3.0.0', capabilities: [candidate] };
}

function v4Contract(overrides = {}) {
  return contract({ authority_role: 'primary', ...overrides });
}

function v4Capability(overrides = {}) {
  const candidate = capability();
  const projectSurface = (surfaceName) =>
    surfaceName === 'local_online' || surfaceName === 'local_offline'
      ? 'desktop_local'
      : surfaceName;
  const surfaceNames = ['web', 'desktop_cloud', 'local_online', 'local_offline', 'native_only'];
  candidate.surfaces = Object.fromEntries(
    surfaceNames.map((surfaceName) => [
      surfaceName,
      {
        ...candidate.surfaces[projectSurface(surfaceName)],
        supporting_authorities: [],
      },
    ]),
  );
  candidate.api_contracts = surfaceNames.flatMap((surfaceName) =>
    candidate.api_contracts
      .filter((entry) => entry.surface === projectSurface(surfaceName))
      .map((entry) => ({
        ...entry,
        surface: surfaceName,
        authority_role: 'primary',
      })),
  );
  candidate.journeys = candidate.journeys.map((journey) => ({
    ...journey,
    mode_policy: Object.fromEntries(
      surfaceNames.map((surfaceName) => [
        surfaceName,
        journey.mode_policy[projectSurface(surfaceName)],
      ]),
    ),
    actions: Object.fromEntries(
      surfaceNames.map((surfaceName) => [
        surfaceName,
        [...journey.actions[projectSurface(surfaceName)]],
      ]),
    ),
    api_contracts: surfaceNames.flatMap((surfaceName) =>
      journey.api_contracts
        .filter((entry) => entry.surface === projectSurface(surfaceName))
        .map((entry) => ({
          ...entry,
          surface: surfaceName,
          authority_role: 'primary',
        })),
    ),
  }));
  return { ...candidate, ...overrides };
}

function v4Manifest(candidate = v4Capability()) {
  return { schema_version: '4.0.0', capabilities: [candidate] };
}

function issueCodes(candidate) {
  return validateParityStructuralClosure(manifest(candidate)).map(({ code }) => code);
}

test('active surfaces close actions, API authority and reason-code structure', () => {
  assert.deepEqual(validateParityStructuralClosure(manifest()), []);
  assert.doesNotThrow(() => assertParityStructuralClosure(manifest()));
});

test('active route-only surfaces may explicitly declare that no service API applies', () => {
  const candidate = capability();
  candidate.kind = 'route_only';
  candidate.surfaces.desktop_cloud = surface({ authority: 'none' });
  candidate.api_contracts = candidate.api_contracts.map((entry) =>
    entry.surface === 'desktop_cloud'
      ? contract({
          method: 'NONE',
          path: 'not_applicable:renderer_owned_route',
          authority: 'none',
        })
      : entry,
  );
  candidate.journeys[0].api_contracts = [
    contract({
      method: 'NONE',
      path: 'not_applicable:renderer_owned_route',
      authority: 'none',
    }),
  ];

  assert.deepEqual(validateParityStructuralClosure(manifest(candidate)), []);
});

test('service-backed surfaces cannot use a no-service declaration as an active contract', () => {
  const candidate = capability();
  candidate.api_contracts = candidate.api_contracts.map((entry) =>
    entry.surface === 'desktop_cloud'
      ? contract({
          method: 'NONE',
          path: 'not_applicable:no_service_contract',
          authority: 'none',
        })
      : entry,
  );

  assert.equal(issueCodes(candidate).includes('active_surface_api_authority_mismatch'), true);
});

test('active surfaces fail closed on missing actions or executable authority contracts', () => {
  const noActions = capability();
  noActions.surfaces.desktop_cloud.allowed_actions = [];
  assert.equal(issueCodes(noActions).includes('active_surface_actions_missing'), true);

  const plannedContract = capability();
  plannedContract.api_contracts = plannedContract.api_contracts.map((entry) =>
    entry.surface === 'desktop_cloud'
      ? contract({
          method: 'NONE',
          path: 'unavailable:desktop_native_route_planned',
          authority: 'none',
        })
      : entry,
  );
  assert.equal(
    issueCodes(plannedContract).includes('active_surface_api_contract_unavailable'),
    true,
  );

  const wrongAuthority = capability();
  wrongAuthority.api_contracts = [
    ...wrongAuthority.api_contracts,
    contract({
      path: '/api/v1/resources/stale-authority',
      authority: 'sidecar',
    }),
  ];
  assert.equal(issueCodes(wrongAuthority).includes('active_surface_api_authority_mismatch'), true);
});

test('availability and reason codes form a deterministic bidirectional closure', () => {
  const availableWithReason = capability();
  availableWithReason.surfaces.desktop_cloud.reason_code = 'unexpected_reason';
  assert.equal(
    issueCodes(availableWithReason).includes('available_surface_reason_code_present'),
    true,
  );

  const degradedWithoutReason = capability();
  degradedWithoutReason.surfaces.desktop_cloud = surface({
    implementation_status: 'partial',
    availability: 'degraded',
    reason_code: null,
  });
  assert.equal(
    issueCodes(degradedWithoutReason).includes('degraded_surface_reason_code_missing'),
    true,
  );

  const unavailableWithoutReason = capability();
  unavailableWithoutReason.surfaces.desktop_local.reason_code = null;
  assert.equal(
    issueCodes(unavailableWithoutReason).includes('inactive_surface_reason_code_missing'),
    true,
  );

  const invalidReason = capability();
  invalidReason.surfaces.desktop_local.reason_code = 'Human readable reason';
  assert.equal(issueCodes(invalidReason).includes('surface_reason_code_invalid'), true);
});

test('active journey rows close actions and mode-matched API authority independently', () => {
  const missingJourneyActions = capability();
  missingJourneyActions.journeys[0].actions.desktop_cloud = [];
  assert.equal(issueCodes(missingJourneyActions).includes('active_journey_actions_missing'), true);

  const missingJourneyContract = capability();
  missingJourneyContract.journeys[0].api_contracts = [];
  assert.equal(
    issueCodes(missingJourneyContract).includes('active_journey_api_contract_missing'),
    true,
  );

  const wrongJourneyAuthority = capability();
  wrongJourneyAuthority.journeys[0].api_contracts = [contract({ authority: 'sidecar' })];
  assert.equal(
    issueCodes(wrongJourneyAuthority).includes('active_journey_api_authority_mismatch'),
    true,
  );
});

test('v4 accepts a primary service authority with declared Electron support', () => {
  const candidate = v4Capability();
  candidate.surfaces.desktop_cloud.supporting_authorities = ['electron'];
  candidate.journeys[0].api_contracts = [
    v4Contract(),
    v4Contract({
      method: 'IPC',
      path: 'electron://dialog/save-file',
      authority: 'electron',
      authority_role: 'supporting',
    }),
  ];

  assert.deepEqual(validateParityStructuralClosure(v4Manifest(candidate)), []);
});

test('v4 rejects undeclared, duplicate, and primary supporting authorities', () => {
  const undeclared = v4Capability();
  undeclared.journeys[0].api_contracts = [
    v4Contract(),
    v4Contract({
      method: 'IPC',
      path: 'electron://dialog/save-file',
      authority: 'electron',
      authority_role: 'supporting',
    }),
  ];
  assert.equal(
    validateParityStructuralClosure(v4Manifest(undeclared)).some(({ code }) =>
      code.includes('supporting_authority_undeclared'),
    ),
    true,
  );

  const invalidSurface = v4Capability();
  invalidSurface.surfaces.desktop_cloud.supporting_authorities = [
    'electron',
    'electron',
    'cloud_service',
  ];
  assert.equal(
    validateParityStructuralClosure(v4Manifest(invalidSurface)).some(
      ({ code }) => code === 'surface_supporting_authorities_invalid',
    ),
    true,
  );
});

test('v4 requires a mode-matched primary contract and rejects unused support declarations', () => {
  const noPrimary = v4Capability();
  noPrimary.surfaces.desktop_cloud.supporting_authorities = ['electron'];
  noPrimary.api_contracts = noPrimary.api_contracts.map((entry) =>
    entry.surface === 'desktop_cloud'
      ? {
          ...entry,
          method: 'IPC',
          path: 'electron://dialog/save-file',
          authority: 'electron',
          authority_role: 'supporting',
        }
      : entry,
  );
  noPrimary.journeys[0].api_contracts = [
    v4Contract({
      method: 'IPC',
      path: 'electron://dialog/save-file',
      authority: 'electron',
      authority_role: 'supporting',
    }),
  ];
  assert.equal(
    validateParityStructuralClosure(v4Manifest(noPrimary)).some(({ code }) =>
      code.includes('primary_authority_missing'),
    ),
    true,
  );

  const unused = v4Capability();
  unused.surfaces.desktop_cloud.supporting_authorities = ['electron'];
  assert.equal(
    validateParityStructuralClosure(v4Manifest(unused)).some(
      ({ code }) => code === 'surface_supporting_authority_unused',
    ),
    true,
  );
});

test('v4 route-only no-service contracts must retain the primary authority role', () => {
  const candidate = v4Capability();
  candidate.surfaces.web = {
    ...candidate.surfaces.web,
    disposition: 'native_equivalent',
    implementation_status: 'implemented',
    availability: 'available',
    reason_code: null,
    authority: 'none',
    allowed_actions: ['view'],
  };
  candidate.journeys[0].mode_policy.web = 'required';
  candidate.journeys[0].actions.web = ['view'];
  candidate.api_contracts = candidate.api_contracts.filter((entry) => entry.surface !== 'web');
  candidate.api_contracts.push(
    v4Contract({
      surface: 'web',
      method: 'NONE',
      path: 'not_applicable:route-only/example',
      authority: 'none',
      authority_role: 'supporting',
    }),
  );
  candidate.journeys[0].api_contracts = candidate.journeys[0].api_contracts.filter(
    (entry) => entry.surface !== 'web',
  );
  candidate.journeys[0].api_contracts.push(
    v4Contract({
      surface: 'web',
      method: 'NONE',
      path: 'not_applicable:route-only/example',
      authority: 'none',
      authority_role: 'supporting',
    }),
  );

  assert.equal(
    validateParityStructuralClosure(v4Manifest(candidate)).some(({ code }) =>
      code.includes('primary_authority_missing'),
    ),
    true,
  );
});

test('active structural failures deterministically downgrade the affected surface', () => {
  const candidate = capability();
  candidate.api_contracts = candidate.api_contracts.map((entry) =>
    entry.surface === 'desktop_cloud'
      ? contract({
          method: 'NONE',
          path: 'unavailable:desktop_native_route_planned',
          authority: 'none',
        })
      : entry,
  );
  const input = manifest(candidate);
  const downgraded = downgradeStructurallyInvalidSurfaces(input);

  assert.equal(input.capabilities[0].surfaces.desktop_cloud.availability, 'available');
  assert.deepEqual(downgraded.capabilities[0].surfaces.desktop_cloud, {
    ...candidate.surfaces.desktop_cloud,
    implementation_status: 'unavailable',
    availability: 'unavailable',
    reason_code: 'parity_structural_active_surface_api_contract_unavailable',
    allowed_actions: [],
  });
  assert.deepEqual(validateParityStructuralClosure(downgraded), []);
});

test('checked-in manifest is structurally closed after deterministic downgrades', () => {
  const checkedInManifest = JSON.parse(
    readFileSync(new URL('parity-manifest.v3.json', contractRoot), 'utf8'),
  );
  const issues = validateParityStructuralClosure(checkedInManifest);
  assert.deepEqual(issues, []);
  assert.doesNotThrow(() => assertParityStructuralClosure(checkedInManifest));
  const invitation = checkedInManifest.capabilities.find(
    ({ id }) => id === 'invitation-acceptance',
  );
  assert.equal(invitation.surfaces.desktop_cloud.availability, 'unavailable');
  assert.equal(
    invitation.surfaces.desktop_cloud.reason_code,
    'renderer_capability_authority_unobserved',
  );
  assert.deepEqual(
    Object.keys(checkedInManifest.capabilities[0].surfaces).sort(),
    [...surfaces].sort(),
  );
});

test('checked-in v4 manifest restores Agent Workspace with compound authority closure', () => {
  const checkedInManifest = JSON.parse(
    readFileSync(new URL('parity-manifest.v4.json', contractRoot), 'utf8'),
  );
  assert.deepEqual(validateParityStructuralClosure(checkedInManifest), []);
  const capability = checkedInManifest.capabilities.find(
    ({ id }) => id === 'agent-workspace-tenant-agent-workspace',
  );
  assert.equal(capability.surfaces.desktop_cloud.availability, 'degraded');
  assert.equal(capability.surfaces.local_online.availability, 'degraded');
  assert.equal(capability.surfaces.local_offline.availability, 'degraded');
  assert.deepEqual(capability.surfaces.desktop_cloud.supporting_authorities, ['electron']);
  assert.deepEqual(capability.surfaces.local_online.supporting_authorities, ['electron']);
  assert.deepEqual(capability.surfaces.local_offline.supporting_authorities, ['electron']);
});

test('standalone checker accepts the structurally closed checked-in manifest', () => {
  const checkerPath = fileURLToPath(
    new URL('../contracts/desktop-web-parity/check-parity-structural-closure.mjs', import.meta.url),
  );
  const result = spawnSync(process.execPath, [checkerPath], {
    encoding: 'utf8',
  });

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Verified structural closure for 66 capabilities/u);
});
