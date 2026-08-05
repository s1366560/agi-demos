import assert from 'node:assert/strict';
import test from 'node:test';

import {
  FULL_ACCESS_WARNING_STORAGE_PREFIX,
  PERMISSION_PRESET_STORAGE_PREFIX,
  acknowledgeFullAccessWarning,
  autoApprovalForPermissionRequest,
  autoApprovalResponseData,
  autoApprovalSubmission,
  fullAccessWarningScope,
  parsePermissionPreset,
  permissionDenialResponseData,
  permissionModeForPreset,
  permissionPresetScope,
  readFullAccessWarningAcknowledged,
  readPermissionPreset,
  writePermissionPreset,
} from '/tmp/agistack-desktop-test-dist/src/features/chat/permissionPresetModel.js';
import { permissionParameterPreview } from '/tmp/agistack-desktop-test-dist/src/features/chat/hitlResponseCardModel.js';
import {
  applyHitlResponseStreamEvent,
  hitlResponsePresentation,
} from '/tmp/agistack-desktop-test-dist/src/features/chat/hitlResponseEventModel.js';

function memoryStorage(initial = {}) {
  const map = new Map(Object.entries(initial));
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => {
      map.set(key, String(value));
    },
    map,
  };
}

function permissionRequest(overrides = {}) {
  return {
    id: 'hitl-1',
    kind: 'permission',
    status: 'pending',
    authority_revision: 3,
    permission: {
      tool_name: 'read_file',
      action: 'execute',
      risk_level: 'low',
      description: 'Read a file',
      allow_remember: true,
    },
    ...overrides,
  };
}

test('parsePermissionPreset only accepts known presets', () => {
  assert.equal(parsePermissionPreset('relaxed'), 'relaxed');
  assert.equal(parsePermissionPreset('full'), 'full');
  assert.equal(parsePermissionPreset('default'), 'default');
  assert.equal(parsePermissionPreset('bypass'), 'default');
  assert.equal(parsePermissionPreset(null), 'default');
});

test('permission presets map to canonical run authorization modes', () => {
  assert.equal(permissionModeForPreset('default'), 'ask');
  assert.equal(permissionModeForPreset('relaxed'), 'automatic');
  assert.equal(permissionModeForPreset('full'), 'full_access');
});

test('preset scope requires both workspace and conversation', () => {
  assert.equal(permissionPresetScope('ws', 'conv'), 'ws\u0000conv');
  assert.equal(permissionPresetScope('', 'conv'), null);
  assert.equal(permissionPresetScope('ws', ''), null);
});

test('preset read/write round-trips per scope with injectable storage', () => {
  const storage = memoryStorage();
  const scopeA = permissionPresetScope('ws', 'conv-a');
  const scopeB = permissionPresetScope('ws', 'conv-b');
  writePermissionPreset(scopeA, 'full', storage);
  writePermissionPreset(scopeB, 'relaxed', storage);
  assert.equal(readPermissionPreset(scopeA, storage), 'full');
  assert.equal(readPermissionPreset(scopeB, storage), 'relaxed');
  assert.equal(readPermissionPreset('ws\u0000conv-c', storage), 'default');
  assert.equal(
    storage.map.get(`${PERMISSION_PRESET_STORAGE_PREFIX}:ws\u0000conv-a`),
    'full',
  );
});

test('preset reads default when storage is unavailable or throws', () => {
  assert.equal(readPermissionPreset('ws\u0000conv', null), 'default');
  const throwing = {
    getItem() {
      throw new Error('denied');
    },
    setItem() {
      throw new Error('denied');
    },
  };
  assert.equal(readPermissionPreset('ws\u0000conv', throwing), 'default');
  writePermissionPreset('ws\u0000conv', 'full', throwing);
});

test('full-access warning persists once per workspace', () => {
  const storage = memoryStorage();
  assert.equal(readFullAccessWarningAcknowledged('ws', storage), false);
  acknowledgeFullAccessWarning('ws', storage);
  assert.equal(readFullAccessWarningAcknowledged('ws', storage), true);
  assert.equal(readFullAccessWarningAcknowledged('other-ws', storage), false);
  assert.equal(
    storage.map.get(`${FULL_ACCESS_WARNING_STORAGE_PREFIX}:ws`),
    'acknowledged',
  );
  assert.equal(fullAccessWarningScope('  '), 'default');
  assert.equal(readFullAccessWarningAcknowledged('ws', null), false);
});

test('default preset never auto-approves', () => {
  assert.equal(autoApprovalForPermissionRequest('default', permissionRequest()), null);
});

test('relaxed preset auto-approves only low-risk permission requests', () => {
  assert.equal(autoApprovalForPermissionRequest('relaxed', permissionRequest()), 'allow');
  assert.equal(
    autoApprovalForPermissionRequest(
      'relaxed',
      permissionRequest({ permission: { risk_level: 'medium' } }),
    ),
    null,
  );
  assert.equal(
    autoApprovalForPermissionRequest(
      'relaxed',
      permissionRequest({ permission: { risk_level: 'high' } }),
    ),
    null,
  );
  assert.equal(
    autoApprovalForPermissionRequest('relaxed', permissionRequest({ kind: 'decision' })),
    null,
  );
  assert.equal(
    autoApprovalForPermissionRequest('relaxed', permissionRequest({ permission: null })),
    null,
  );
});

test('full preset auto-approves every permission request regardless of risk', () => {
  assert.equal(autoApprovalForPermissionRequest('full', permissionRequest()), 'allow');
  assert.equal(
    autoApprovalForPermissionRequest(
      'full',
      permissionRequest({ permission: { risk_level: 'high' } }),
    ),
    'allow',
  );
  assert.equal(
    autoApprovalForPermissionRequest('full', permissionRequest({ kind: 'clarification' })),
    null,
  );
});

test('auto-approval response data carries truthful preset markers', () => {
  assert.deepEqual(autoApprovalResponseData('relaxed'), {
    action: 'allow',
    granted: true,
    scope: 'once',
    auto_approved: true,
    preset: 'relaxed',
  });
});

test('autoApprovalSubmission builds an idempotent permission response', () => {
  const submission = autoApprovalSubmission(permissionRequest(), 'full');
  assert.equal(submission.requestId, 'hitl-1');
  assert.equal(submission.hitlType, 'permission');
  assert.equal(submission.expectedRevision, 3);
  assert.equal(submission.idempotencyKey, 'hitl-1:3:preset-auto:full');
  assert.equal(submission.responseData.granted, true);
  assert.equal(submission.responseData.auto_approved, true);
  assert.equal(
    autoApprovalSubmission(permissionRequest(), 'default'),
    null,
  );
  const unversioned = autoApprovalSubmission(
    permissionRequest({ authority_revision: null }),
    'relaxed',
  );
  assert.equal('expectedRevision' in unversioned, false);
  assert.equal(unversioned.idempotencyKey, 'hitl-1:unversioned:preset-auto:relaxed');
});

test('denial payload matches the legacy shape unless feedback is present', () => {
  assert.deepEqual(permissionDenialResponseData(), {
    action: 'deny',
    granted: false,
    scope: 'once',
  });
  assert.deepEqual(permissionDenialResponseData('   '), {
    action: 'deny',
    granted: false,
    scope: 'once',
  });
  assert.deepEqual(permissionDenialResponseData('  use Jest instead  '), {
    action: 'deny',
    granted: false,
    scope: 'once',
    feedback: 'use Jest instead',
  });
});

test('permission parameter preview reads structured tool input from the payload', () => {
  const fromMetadata = permissionParameterPreview({
    id: 'p1',
    type: 'permission_asked',
    payload: { metadata: { tool: 'shell_command', input: { command: 'pnpm test' } } },
  });
  assert.equal(fromMetadata, JSON.stringify({ command: 'pnpm test' }, null, 2));

  const fromDetails = permissionParameterPreview({
    id: 'p2',
    type: 'permission_asked',
    payload: { details: { tool: 'shell_command', input: { command: 'ls', path: '/tmp' } } },
  });
  assert.equal(fromDetails, JSON.stringify({ command: 'ls', path: '/tmp' }, null, 2));

  const wholeDetailsFallback = permissionParameterPreview({
    id: 'p3',
    type: 'permission_asked',
    payload: { details: { tool: 'read_file' } },
  });
  assert.equal(wholeDetailsFallback, JSON.stringify({ tool: 'read_file' }, null, 2));

  const bareCommand = permissionParameterPreview({
    id: 'p4',
    type: 'permission_asked',
    payload: { command: 'git status' },
  });
  assert.equal(bareCommand, 'git status');

  assert.equal(permissionParameterPreview({ id: 'p5', type: 'permission_asked' }), null);
  assert.equal(
    permissionParameterPreview({ id: 'p6', type: 'permission_asked', payload: {} }),
    null,
  );
});

test('permission replied events fold the auto-approval preset marker', () => {
  const request = {
    id: 'permission-1',
    type: 'permission_asked',
    requestId: 'permission-1',
    question: 'Allow?',
  };
  const { handled, items } = applyHitlResponseStreamEvent([request], {
    type: 'permission_replied',
    data: { request_id: 'permission-1', granted: true, auto_approved: true, preset: 'relaxed' },
  });
  assert.equal(handled, true);
  assert.equal(items[0].answered, true);
  assert.equal(items[0].granted, true);
  assert.equal(items[0].autoApprovalPreset, 'relaxed');

  const presentation = hitlResponsePresentation(items[0], 'permission');
  assert.equal(presentation.labelKey, 'chat.response.permissionAuto');
  assert.equal(presentation.valueKey, 'chat.permissionPreset.relaxed');
});

test('nested response_data markers are honored and denials never claim presets', () => {
  const request = {
    id: 'permission-2',
    type: 'permission_asked',
    requestId: 'permission-2',
  };
  const nested = applyHitlResponseStreamEvent([request], {
    type: 'permission_replied',
    data: {
      request_id: 'permission-2',
      response_data: { granted: true, auto_approved: true, preset: 'full' },
    },
  });
  assert.equal(nested.items[0].autoApprovalPreset, 'full');
  assert.equal(nested.items[0].granted, true);
  const nestedPresentation = hitlResponsePresentation(nested.items[0], 'permission');
  assert.equal(nestedPresentation.labelKey, 'chat.response.permissionAuto');
  assert.equal(nestedPresentation.valueKey, 'chat.permissionPreset.full');

  const denied = applyHitlResponseStreamEvent([request], {
    type: 'permission_replied',
    data: { request_id: 'permission-2', granted: false, auto_approved: true, preset: 'full' },
  });
  const deniedPresentation = hitlResponsePresentation(denied.items[0], 'permission');
  assert.equal(deniedPresentation.labelKey, 'chat.response.permission');
  assert.equal(deniedPresentation.valueKey, 'chat.response.denied');
});
