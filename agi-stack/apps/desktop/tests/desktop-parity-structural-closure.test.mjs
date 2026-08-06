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

  assert.equal(
    issueCodes(candidate).includes('active_surface_api_authority_mismatch'),
    true,
  );
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
    contract({ path: '/api/v1/resources/stale-authority', authority: 'sidecar' }),
  ];
  assert.equal(
    issueCodes(wrongAuthority).includes('active_surface_api_authority_mismatch'),
    true,
  );
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
  assert.equal(
    issueCodes(invalidReason).includes('surface_reason_code_invalid'),
    true,
  );
});

test('active journey rows close actions and mode-matched API authority independently', () => {
  const missingJourneyActions = capability();
  missingJourneyActions.journeys[0].actions.desktop_cloud = [];
  assert.equal(
    issueCodes(missingJourneyActions).includes('active_journey_actions_missing'),
    true,
  );

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
    reason_code:
      'parity_structural_active_surface_api_contract_unavailable',
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
  assert.deepEqual(Object.keys(checkedInManifest.capabilities[0].surfaces).sort(), [
    ...surfaces,
  ].sort());
});

test('standalone checker accepts the structurally closed checked-in manifest', () => {
  const checkerPath = fileURLToPath(
    new URL(
      '../contracts/desktop-web-parity/check-parity-structural-closure.mjs',
      import.meta.url,
    ),
  );
  const result = spawnSync(process.execPath, [checkerPath], {
    encoding: 'utf8',
  });

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Verified structural closure for 66 capabilities/u);
});
