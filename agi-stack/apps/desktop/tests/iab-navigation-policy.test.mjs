import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  evaluateIabNavigation,
  evaluateIabWindowOpen,
  isIabPermissionAllowed,
} = require('/tmp/agistack-desktop-test-dist/electron/main/iab/iabNavigationPolicy.js');

test('iab navigation allows http, https, and about:blank only', () => {
  assert.deepEqual(evaluateIabNavigation('https://example.com/path?q=1'), {
    allowed: true,
    reasonCode: 'allowed',
  });
  assert.equal(evaluateIabNavigation('http://intranet.local/').allowed, true);
  assert.equal(evaluateIabNavigation('about:blank').allowed, true);

  assert.equal(evaluateIabNavigation('file:///etc/passwd').allowed, false);
  assert.equal(evaluateIabNavigation('file:///etc/passwd').reasonCode, 'protocol_not_allowed');
  assert.equal(evaluateIabNavigation('javascript:alert(1)').allowed, false);
  assert.equal(evaluateIabNavigation('data:text/html,<b>x</b>').allowed, false);
  assert.equal(evaluateIabNavigation('chrome://settings').allowed, false);
  assert.equal(evaluateIabNavigation('agistack://app/index.html').allowed, false);
  assert.equal(evaluateIabNavigation('about:config').allowed, false);
  assert.equal(evaluateIabNavigation('about:config').reasonCode, 'about_url_not_allowed');
});

test('iab navigation rejects malformed and credentialed URLs', () => {
  assert.equal(evaluateIabNavigation('not a url').allowed, false);
  assert.equal(evaluateIabNavigation('not a url').reasonCode, 'url_invalid');
  assert.equal(evaluateIabNavigation('').allowed, false);
  assert.equal(evaluateIabNavigation(null).allowed, false);
  assert.equal(evaluateIabNavigation(42).allowed, false);
  assert.equal(evaluateIabNavigation('https://user:pass@example.com/').allowed, false);
});

test('iab window.open routes navigable targets to a new tab and denies the rest', () => {
  assert.deepEqual(evaluateIabWindowOpen('https://example.com/popup'), {
    action: 'new-tab',
    url: 'https://example.com/popup',
  });
  assert.deepEqual(evaluateIabWindowOpen('file:///etc/passwd'), {
    action: 'deny',
    url: null,
  });
  assert.deepEqual(evaluateIabWindowOpen('javascript:alert(1)'), {
    action: 'deny',
    url: null,
  });
});

test('iab views grant no permissions by default', () => {
  assert.equal(isIabPermissionAllowed(), false);
});
