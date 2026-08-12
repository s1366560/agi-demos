import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  createAccessibilityWebSocketFixture,
  accessibilityWebSocketStateFrame,
} from '../browser-qa/accessibility-websocket-fixture.mjs';

const scope = Object.freeze({
  tenantId: 'accessibility-tenant',
  projectId: 'accessibility-project',
});

test('accessibility WebSocket fixture emits scoped deterministic state frames', () => {
  assert.deepEqual(
    JSON.parse(accessibilityWebSocketStateFrame('baseline', scope)),
    {
      type: 'accessibility_authority_observed',
      event_id: 'accessibility-event-1',
      tenant_id: scope.tenantId,
      project_id: scope.projectId,
    },
  );
  assert.equal(accessibilityWebSocketStateFrame('empty', scope), null);
  assert.deepEqual(
    JSON.parse(accessibilityWebSocketStateFrame('forbidden', scope)),
    {
      type: 'error',
      code: 'CONVERSATION_ACCESS_DENIED',
      reason_code: 'accessibility_fixture_forbidden',
      tenant_id: scope.tenantId,
      project_id: scope.projectId,
    },
  );
  assert.equal(
    JSON.parse(accessibilityWebSocketStateFrame('conflict', scope)).code,
    'MESSAGE_ID_CONFLICT',
  );
  assert.equal(
    JSON.parse(accessibilityWebSocketStateFrame('error', scope)).code,
    'ACCESSIBILITY_FIXTURE_ERROR',
  );
});

test('accessibility WebSocket fixture holds loading connections until released', async () => {
  const fixture = createAccessibilityWebSocketFixture(scope);
  const route = fakeWebSocketRoute();
  fixture.setState('loading');

  const handled = fixture.handle(route);
  assert.deepEqual(fixture.observation(), {
    state: 'loading',
    connections: 1,
    receivedMessages: 0,
    pendingConnections: 1,
  });

  fixture.releasePending();
  await handled;
  assert.equal(fixture.observation().pendingConnections, 0);
  assert.deepEqual(route.sent, []);
});

test('accessibility WebSocket fixture records subscriptions and rejects unknown states', async () => {
  const fixture = createAccessibilityWebSocketFixture(scope);
  const route = fakeWebSocketRoute();
  fixture.setState('forbidden');
  await fixture.handle(route);
  route.receive(JSON.stringify({ type: 'subscribe_status', project_id: scope.projectId }));

  assert.equal(route.sent.length, 1);
  assert.equal(fixture.observation().receivedMessages, 1);
  assert.throws(() => fixture.setState('unknown'), /accessibility_websocket_state_invalid/u);
});

function fakeWebSocketRoute() {
  let messageHandler = () => {};
  return {
    sent: [],
    onMessage(handler) {
      messageHandler = handler;
    },
    send(message) {
      this.sent.push(message);
    },
    receive(message) {
      messageHandler(message);
    },
  };
}
