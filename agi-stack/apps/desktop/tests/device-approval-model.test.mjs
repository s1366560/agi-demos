import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  isCompleteDeviceApprovalCode,
  normalizeDeviceApprovalCode,
  readDeviceApprovalCodeFromHash,
} = require('/tmp/agistack-desktop-test-dist/src/features/device-approval/deviceApprovalModel.js');

test('device approval code normalization matches the Web structural contract', () => {
  assert.equal(normalizeDeviceApprovalCode('ab-cd 23_45!ignored'), 'ABCD2345');
  assert.equal(normalizeDeviceApprovalCode('IO01abcd'), 'IO01ABCD');
  assert.equal(normalizeDeviceApprovalCode('123456789'), '12345678');
  assert.equal(isCompleteDeviceApprovalCode('ABCD2345'), true);
  assert.equal(isCompleteDeviceApprovalCode('ABCD234'), false);
  assert.equal(isCompleteDeviceApprovalCode('ABCD-345'), false);
});

test('device approval deep link accepts Web query aliases without exposing malformed values', () => {
  assert.equal(
    readDeviceApprovalCodeFromHash('#/device?user_code=ab-cd-2345'),
    'ABCD2345',
  );
  assert.equal(
    readDeviceApprovalCodeFromHash('#/device?code=io01abcd'),
    'IO01ABCD',
  );
  assert.equal(
    readDeviceApprovalCodeFromHash('#/device?user_code=first&user_code=second'),
    '',
  );
  assert.equal(
    readDeviceApprovalCodeFromHash('#/device?user_code=ABCD2345&code=EFGH6789'),
    '',
  );
  assert.equal(
    readDeviceApprovalCodeFromHash('#/device?user_code=%E0%A4%A'),
    '',
  );
  assert.equal(
    readDeviceApprovalCodeFromHash('#/untrusted?user_code=ABCD2345'),
    '',
  );
});
